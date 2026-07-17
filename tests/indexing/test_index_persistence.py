from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.domain.entities import CodeEntity
from backend.app.domain.index_manifest import IndexedFile, SymbolChunk
from backend.app.indexing.stable_ids import code_entity_id, repository_identity, symbol_chunk_id, text_content_hash
from backend.app.persistence.index_store import IndexArtifacts, IndexBusyError, StructuredIndexStore
from backend.app.persistence.migration_runner import migrate_database


def _artifacts(repo_id: str, path: str = "pkg/a.py", text: str = "def run():\n    pass\n") -> IndexArtifacts:
    digest = text_content_hash(text)
    entity_id = code_entity_id(repo_id, "function", path, "pkg.a.run")
    entity = CodeEntity(
        id=entity_id, repo_id=repo_id, entity_type="function", path=path, name="run",
        qualified_name="pkg.a.run", module_name="pkg.a", source_code=text, content_hash=digest,
    )
    chunk = SymbolChunk(
        id=symbol_chunk_id(entity_id, "function", 0, digest), repo_id=repo_id, entity_id=entity_id,
        entity_kind="code", chunk_type="function", path=path, ordinal=0, text=text,
        content_hash=digest, char_count=len(text),
    )
    indexed = IndexedFile(
        path=path, kind="python", content_hash=digest, size_bytes=len(text.encode()), parse_status="success",
        entity_count=1, edge_count=0, chunk_count=1,
    )
    return IndexArtifacts([indexed], [entity], [], [], [], [chunk])


def _begin(store: StructuredIndexStore, repo_id: str, fingerprint: str):
    return store.begin_version(
        repo_id=repo_id, identity_mode="explicit", repository_key=repo_id,
        display_name="repo", input_hash=fingerprint,
    )


def test_schema_persists_chunks_files_and_reuses_identical_input(tmp_path) -> None:
    path = tmp_path / "index.sqlite3"
    store = StructuredIndexStore(path)
    repo_id = repository_identity("task", "persist/repo")[0]
    lease = _begin(store, repo_id, "hash-a")
    store.mark_ready(lease)
    store.activate(lease, _artifacts(repo_id))
    reused = _begin(store, repo_id, "hash-a")

    assert reused.reused is True
    assert reused.index_version_id == lease.index_version_id
    assert store.version_counts(lease.index_version_id) == {
        "file_count": 1, "code_entity_count": 1, "paper_entity_count": 0,
        "edge_count": 0, "evidence_count": 0, "chunk_count": 1,
    }
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT path FROM indexed_files").fetchone()[0] == "pkg/a.py"
        assert connection.execute("SELECT chunk_type FROM symbol_chunks").fetchone()[0] == "function"


def test_new_version_supersedes_old_and_rollback_is_atomic(tmp_path) -> None:
    store = StructuredIndexStore(tmp_path / "index.sqlite3")
    repo_id = repository_identity("task", "versions/repo")[0]
    first = _begin(store, repo_id, "hash-a")
    store.mark_ready(first)
    store.activate(first, _artifacts(repo_id))
    second = _begin(store, repo_id, "hash-b")
    store.mark_ready(second)
    store.activate(second, _artifacts(repo_id, path="pkg/b.py", text="def next():\n    pass\n"))

    assert store.version_row(first.index_version_id)["status"] == "superseded"
    assert store.version_row(second.index_version_id)["status"] == "active"
    with pytest.raises(RuntimeError, match="explicit version rollback"):
        _begin(store, repo_id, "hash-a")
    store.rollback_to_version(repo_id, first.index_version_id)
    assert store.version_row(first.index_version_id)["status"] == "active"
    assert store.version_row(second.index_version_id)["status"] == "superseded"


def test_build_lease_does_not_hold_write_transaction_and_busy_is_retryable(tmp_path) -> None:
    path = tmp_path / "index.sqlite3"
    store = StructuredIndexStore(path, busy_timeout_seconds=0.05)
    repo_id = repository_identity("task", "busy/repo")[0]
    lease = _begin(store, repo_id, "hash-a")

    # A separate writer can acquire SQLite immediately while the long build is
    # conceptually running between begin_version and mark_ready.
    with sqlite3.connect(path, timeout=0.05) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE repositories SET display_name='other' WHERE repo_id=?", (repo_id,))
        connection.commit()
    with pytest.raises(IndexBusyError):
        _begin(store, repo_id, "hash-b")
    store.mark_failed(lease, {"error_code": "test"})


def test_failed_version_has_bounded_retry_and_old_active_survives(tmp_path) -> None:
    store = StructuredIndexStore(tmp_path / "index.sqlite3", max_retries=2)
    repo_id = repository_identity("task", "retry/repo")[0]
    active = _begin(store, repo_id, "active")
    store.mark_ready(active)
    store.activate(active, _artifacts(repo_id))
    failed = _begin(store, repo_id, "failed")
    store.mark_failed(failed, {"error_code": "parse", "retryable": False})
    retry = _begin(store, repo_id, "failed")
    assert retry.index_version_id == failed.index_version_id
    assert store.version_row(retry.index_version_id)["retry_count"] == 1
    store.mark_failed(retry, {"error_code": "parse", "retryable": False})
    retry_two = _begin(store, repo_id, "failed")
    store.mark_failed(retry_two, {"error_code": "parse", "retryable": False})
    with pytest.raises(RuntimeError, match="retry limit"):
        _begin(store, repo_id, "failed")
    assert store.version_row(active.index_version_id)["status"] == "active"


def test_same_input_waits_and_reuses_while_different_input_is_busy(tmp_path) -> None:
    store = StructuredIndexStore(tmp_path / "index.sqlite3", same_input_wait_seconds=2)
    repo_id = repository_identity("task", "concurrent/repo")[0]
    lease = _begin(store, repo_id, "same")
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(_begin, store, repo_id, "same")
        with pytest.raises(IndexBusyError):
            _begin(store, repo_id, "different")
        store.mark_ready(lease)
        store.activate(lease, _artifacts(repo_id))
        reused = waiting.result(timeout=3)
    assert reused.reused is True
    assert reused.index_version_id == lease.index_version_id


def test_different_repositories_can_start_concurrently(tmp_path) -> None:
    store = StructuredIndexStore(tmp_path / "index.sqlite3", busy_timeout_seconds=0.2)
    repo_ids = [repository_identity("task", f"parallel/{index}")[0] for index in range(6)]
    with ThreadPoolExecutor(max_workers=6) as executor:
        leases = list(executor.map(lambda item: _begin(store, item, "hash"), repo_ids))
    assert len({lease.index_version_id for lease in leases}) == len(repo_ids)
    for lease in leases:
        store.mark_failed(lease, {"error_code": "test_cleanup"})


def test_stale_lease_is_failed_before_new_build_starts(tmp_path) -> None:
    path = tmp_path / "index.sqlite3"
    store = StructuredIndexStore(path, same_input_wait_seconds=0)
    repo_id = repository_identity("task", "stale/repo")[0]
    stale = _begin(store, repo_id, "old")
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE index_versions SET lease_expires_at=? WHERE index_version_id=?",
            (expired, stale.index_version_id),
        )
    current = _begin(store, repo_id, "new")
    assert store.version_row(stale.index_version_id)["status"] == "failed"
    assert store.version_row(current.index_version_id)["status"] == "building"


def test_activation_validation_rolls_back_without_replacing_active(tmp_path) -> None:
    store = StructuredIndexStore(tmp_path / "index.sqlite3")
    repo_id = repository_identity("task", "rollback/repo")[0]
    active = _begin(store, repo_id, "active")
    store.mark_ready(active)
    store.activate(active, _artifacts(repo_id))
    invalid = _begin(store, repo_id, "invalid")
    store.mark_ready(invalid)
    artifacts = _artifacts(repo_id)
    artifacts.chunks[0].entity_id = "missing"
    with pytest.raises(ValueError, match="missing entity"):
        store.activate(invalid, artifacts)
    store.mark_failed(invalid, {"error_code": "invalid_reference"})
    assert store.version_row(active.index_version_id)["status"] == "active"


def test_migration_failure_rolls_back_schema_version(monkeypatch, tmp_path) -> None:
    import backend.app.persistence.migration_runner as runner

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_structured_index.sql").write_text(
        "BEGIN IMMEDIATE; CREATE TABLE partial(value TEXT); INVALID SQL; COMMIT;", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", migrations)
    path = tmp_path / "broken.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        migrate_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='partial'"
        ).fetchone()[0] == 0


def test_retryable_sqlite_io_error_uses_bounded_retry(monkeypatch, tmp_path) -> None:
    store = StructuredIndexStore(tmp_path / "index.sqlite3", max_retries=3)
    store.ensure_schema()
    original = store._connect
    attempts = 0

    def flaky_connect():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("disk I/O error")
        return original()

    monkeypatch.setattr(store, "_connect", flaky_connect)
    repo_id = repository_identity("task", "io-retry/repo")[0]
    lease = _begin(store, repo_id, "hash")
    assert lease.reused is False
    assert attempts == 3
