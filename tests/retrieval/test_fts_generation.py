from __future__ import annotations

import sqlite3

import pytest

from backend.app.persistence.fts_generation_store import FTSGenerationError, FTSGenerationStore
from backend.app.retrieval.schemas import RetrievalDocument, RetrievalFilter


def _document(*, version: str, chunk_id: str = "chunk-stable", text: str = "def forward(x): return x"):
    return RetrievalDocument(
        chunk_id=chunk_id, entity_id="entity-forward", repo_id="repo-a", index_version_id=version,
        entity_kind="code", entity_type="function", chunk_type="function", path="models/net.py",
        qualified_name="models.net.SimpleNet.forward", start_line=10, end_line=11,
        text=text, content_hash=f"hash-{text}",
    )


def _filters(version: str) -> RetrievalFilter:
    return RetrievalFilter(repo_id="repo-a", index_version_id=version)


def test_repeated_fts_sync_is_idempotent(tmp_path) -> None:
    store = FTSGenerationStore(tmp_path / "fts.sqlite3")
    first, reused_first = store.sync(
        repo_id="repo-a", index_version_id="idx-1", profile_hash="profile-1",
        documents=[_document(version="idx-1")],
    )
    second, reused_second = store.sync(
        repo_id="repo-a", index_version_id="idx-1", profile_hash="profile-1",
        documents=[_document(version="idx-1")],
    )
    assert first == second
    assert not reused_first and reused_second
    hits = store.search(
        query_text="models.net.SimpleNet.forward", filters=_filters("idx-1"),
        profile_hash="profile-1", top_k=5,
    )
    assert [hit.chunk_id for hit in hits] == ["chunk-stable"]
    assert hits[0].metadata["exact_boost"] == 10.0


def test_failed_fts_sync_keeps_previous_ready_generation(tmp_path) -> None:
    store = FTSGenerationStore(tmp_path / "fts.sqlite3")
    ready_id, _ = store.sync(
        repo_id="repo-a", index_version_id="idx-1", profile_hash="profile-1",
        documents=[_document(version="idx-1")],
    )
    with pytest.raises(FTSGenerationError):
        store.sync(
            repo_id="repo-a", index_version_id="idx-1", profile_hash="profile-1",
            documents=[_document(version="idx-1", text="def changed(): return 2")],
            fail_before_activation=True,
        )
    assert store.ready_generation(
        repo_id="repo-a", index_version_id="idx-1", profile_hash="profile-1"
    )["generation_id"] == ready_id


def test_query_never_reads_building_fts_generation(tmp_path) -> None:
    path = tmp_path / "fts.sqlite3"
    store = FTSGenerationStore(path)
    store.ensure_schema()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT INTO retrieval_fts_generations(
                   generation_id, repo_id, index_version_id, profile_hash, status,
                   document_count, content_hash, created_at
               ) VALUES ('building-1', 'repo-a', 'idx-1', 'profile-1', 'building', 0, 'hash', 'now')"""
        )
    with pytest.raises(FTSGenerationError) as error:
        store.search(
            query_text="forward", filters=_filters("idx-1"), profile_hash="profile-1", top_k=5
        )
    assert error.value.error_code == "fts_generation_not_ready"


def test_delete_one_version_keeps_other_versions(tmp_path) -> None:
    store = FTSGenerationStore(tmp_path / "fts.sqlite3")
    for version in ("idx-1", "idx-2"):
        store.sync(
            repo_id="repo-a", index_version_id=version, profile_hash="profile-1",
            documents=[_document(version=version)],
        )
    store.delete_version(repo_id="repo-a", index_version_id="idx-1")
    assert store.ready_generation(
        repo_id="repo-a", index_version_id="idx-1", profile_hash="profile-1"
    ) is None
    assert store.ready_generation(
        repo_id="repo-a", index_version_id="idx-2", profile_hash="profile-1"
    ) is not None
