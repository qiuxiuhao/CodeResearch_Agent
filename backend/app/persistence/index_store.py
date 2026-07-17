from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, TypeVar
from uuid import uuid4

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import IndexedFile, SymbolChunk
from backend.app.persistence.migration_runner import migrate_database


T = TypeVar("T")


class IndexBusyError(RuntimeError):
    retryable = True


@dataclass(frozen=True)
class VersionLease:
    index_version_id: str
    sequence: int
    lease_owner: str | None
    reused: bool
    activated_at: str | None = None


@dataclass(frozen=True)
class IndexArtifacts:
    indexed_files: list[IndexedFile]
    code_entities: list[CodeEntity]
    paper_entities: list[PaperEntity]
    edges: list[KnowledgeEdge]
    evidence: list[EvidenceRef]
    chunks: list[SymbolChunk]


class StructuredIndexStore:
    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_seconds: float = 5.0,
        max_retries: int = 3,
        lease_seconds: int = 300,
        same_input_wait_seconds: float = 5.0,
    ) -> None:
        self.path = Path(path)
        self.busy_timeout_seconds = busy_timeout_seconds
        self.max_retries = max_retries
        self.lease_seconds = lease_seconds
        self.same_input_wait_seconds = same_input_wait_seconds

    def ensure_schema(self) -> None:
        migrate_database(self.path)

    def begin_version(
        self,
        *,
        repo_id: str,
        identity_mode: str,
        repository_key: str | None,
        display_name: str,
        input_hash: str,
    ) -> VersionLease:
        self.ensure_schema()

        def operation(connection: sqlite3.Connection) -> VersionLease:
            now = _now()
            connection.execute(
                """INSERT INTO repositories(
                    repo_id, identity_mode, repository_key, display_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id) DO UPDATE SET
                    display_name=excluded.display_name, updated_at=excluded.updated_at""",
                (repo_id, identity_mode, repository_key, display_name, now, now),
            )
            existing = connection.execute(
                "SELECT * FROM index_versions WHERE repo_id=? AND input_hash=?",
                (repo_id, input_hash),
            ).fetchone()
            if existing is not None:
                return self._resume_or_reuse(connection, existing, repo_id)

            active_build = connection.execute(
                "SELECT * FROM index_versions WHERE repo_id=? AND status IN ('building', 'ready')",
                (repo_id,),
            ).fetchone()
            if active_build is not None:
                if not _lease_expired(active_build["lease_expires_at"]):
                    raise IndexBusyError(f"Repository {repo_id} already has an index build in progress.")
                connection.execute(
                    "UPDATE index_versions SET status='failed', failed_at=?, error_json=?, lease_owner=NULL, lease_expires_at=NULL "
                    "WHERE index_version_id=?",
                    (now, _json({"error_code": "stale_lease", "retryable": True}), active_build["index_version_id"]),
                )

            sequence = int(connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM index_versions WHERE repo_id=?", (repo_id,)
            ).fetchone()[0])
            version_id = _version_id(repo_id, sequence, input_hash)
            owner = uuid4().hex
            connection.execute(
                """INSERT INTO index_versions(
                    index_version_id, repo_id, sequence, input_hash, status, retry_count,
                    lease_owner, lease_expires_at, created_at
                ) VALUES (?, ?, ?, ?, 'building', 0, ?, ?, ?)""",
                (version_id, repo_id, sequence, input_hash, owner, _lease_expiry(self.lease_seconds), now),
            )
            return VersionLease(version_id, sequence, owner, False)

        try:
            return self._write(operation)
        except IndexBusyError:
            # Identical work may be shared: wait only when this exact input is
            # already building. A competing input for the same repository
            # remains an immediate, retryable index_busy response.
            row = self._version_for_input(repo_id, input_hash)
            if row is None or row["status"] not in {"building", "ready"}:
                raise
            deadline = time.monotonic() + self.same_input_wait_seconds
            while time.monotonic() < deadline:
                time.sleep(0.05)
                row = self._version_for_input(repo_id, input_hash)
                if row is None:
                    break
                if row["status"] == "active":
                    return VersionLease(
                        row["index_version_id"], int(row["sequence"]), None, True, row["activated_at"]
                    )
                if row["status"] in {"failed", "superseded"}:
                    return self._write(operation)
            raise IndexBusyError(f"Repository {repo_id} has the same index build in progress.")

    def mark_ready(self, lease: VersionLease) -> None:
        if lease.reused:
            return

        def operation(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """UPDATE index_versions SET status='ready', ready_at=?, lease_expires_at=?
                   WHERE index_version_id=? AND status='building' AND lease_owner=?""",
                (_now(), _lease_expiry(self.lease_seconds), lease.index_version_id, lease.lease_owner),
            )
            if cursor.rowcount != 1:
                raise IndexBusyError("Structured index lease was lost before ready state.")

        self._write(operation)

    def activate(self, lease: VersionLease, artifacts: IndexArtifacts) -> str:
        if lease.reused:
            return lease.activated_at or _now()
        self._validate_artifacts(artifacts)

        def operation(connection: sqlite3.Connection) -> str:
            row = connection.execute(
                "SELECT repo_id, status, lease_owner FROM index_versions WHERE index_version_id=?",
                (lease.index_version_id,),
            ).fetchone()
            if row is None or row["status"] != "ready" or row["lease_owner"] != lease.lease_owner:
                raise IndexBusyError("Structured index lease was lost before activation.")
            self._replace_artifacts(connection, lease.index_version_id, artifacts)
            self._validate_persisted_counts(connection, lease.index_version_id, artifacts)
            activated_at = _now()
            connection.execute(
                "UPDATE index_versions SET status='superseded' WHERE repo_id=? AND status='active'",
                (row["repo_id"],),
            )
            connection.execute(
                """UPDATE index_versions SET status='active', activated_at=?, lease_owner=NULL,
                   lease_expires_at=NULL, error_json=NULL WHERE index_version_id=?""",
                (activated_at, lease.index_version_id),
            )
            connection.execute(
                "UPDATE repositories SET active_version_id=?, updated_at=? WHERE repo_id=?",
                (lease.index_version_id, activated_at, row["repo_id"]),
            )
            return activated_at

        return self._write(operation)

    def mark_failed(self, lease: VersionLease, error: dict) -> None:
        if lease.reused:
            return

        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                """UPDATE index_versions SET status='failed', failed_at=?, error_json=?,
                   lease_owner=NULL, lease_expires_at=NULL
                   WHERE index_version_id=? AND status IN ('building', 'ready')""",
                (_now(), _json(error), lease.index_version_id),
            )

        self._write(operation)

    def rollback_to_version(self, repo_id: str, index_version_id: str) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            target = connection.execute(
                "SELECT status FROM index_versions WHERE repo_id=? AND index_version_id=?",
                (repo_id, index_version_id),
            ).fetchone()
            if target is None or target["status"] not in {"active", "superseded"}:
                raise ValueError("Rollback target must be an active or superseded version.")
            connection.execute(
                "UPDATE index_versions SET status='superseded' WHERE repo_id=? AND status='active'",
                (repo_id,),
            )
            connection.execute(
                "UPDATE index_versions SET status='active', activated_at=? WHERE index_version_id=?",
                (_now(), index_version_id),
            )
            connection.execute(
                "UPDATE repositories SET active_version_id=?, updated_at=? WHERE repo_id=?",
                (index_version_id, _now(), repo_id),
            )

        self._write(operation)

    def version_counts(self, index_version_id: str) -> dict[str, int]:
        self.ensure_schema()
        tables = {
            "file_count": "indexed_files",
            "code_entity_count": "code_entities",
            "paper_entity_count": "paper_entities",
            "edge_count": "knowledge_edges",
            "evidence_count": "evidence_refs",
            "chunk_count": "symbol_chunks",
        }
        with self._connect() as connection:
            return {
                key: int(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE index_version_id=?", (index_version_id,)
                ).fetchone()[0])
                for key, table in tables.items()
            }

    def version_row(self, index_version_id: str) -> dict | None:
        self.ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM index_versions WHERE index_version_id=?", (index_version_id,)
            ).fetchone()
        return dict(row) if row else None

    def _version_for_input(self, repo_id: str, input_hash: str) -> dict | None:
        self.ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM index_versions WHERE repo_id=? AND input_hash=?", (repo_id, input_hash)
            ).fetchone()
        return dict(row) if row else None

    def resolution_counts(self, index_version_id: str) -> dict[str, int]:
        self.ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT resolution_type, COUNT(*) FROM knowledge_edges
                   WHERE index_version_id=? AND resolution_type IN ('unresolved', 'ambiguous')
                   GROUP BY resolution_type""",
                (index_version_id,),
            ).fetchall()
        values = {row[0]: int(row[1]) for row in rows}
        return {"unresolved": values.get("unresolved", 0), "ambiguous": values.get("ambiguous", 0)}

    def _resume_or_reuse(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        repo_id: str,
    ) -> VersionLease:
        status = row["status"]
        if status == "active":
            return VersionLease(row["index_version_id"], row["sequence"], None, True, row["activated_at"])
        if status == "superseded":
            raise RuntimeError(
                "The matching structured index version is superseded; use explicit version rollback to reactivate it."
            )
        if status in {"building", "ready"} and not _lease_expired(row["lease_expires_at"]):
            raise IndexBusyError(f"Repository {repo_id} already has the same index build in progress.")
        if int(row["retry_count"]) >= self.max_retries:
            raise RuntimeError("Structured index retry limit reached.")
        competing = connection.execute(
            """SELECT index_version_id FROM index_versions
               WHERE repo_id=? AND status IN ('building', 'ready') AND index_version_id<>?""",
            (repo_id, row["index_version_id"]),
        ).fetchone()
        if competing is not None:
            raise IndexBusyError(f"Repository {repo_id} already has another index build in progress.")
        owner = uuid4().hex
        connection.execute(
            """UPDATE index_versions SET status='building', retry_count=retry_count+1,
               lease_owner=?, lease_expires_at=?, error_json=NULL, failed_at=NULL
               WHERE index_version_id=?""",
            (owner, _lease_expiry(self.lease_seconds), row["index_version_id"]),
        )
        return VersionLease(row["index_version_id"], row["sequence"], owner, False)

    def _replace_artifacts(
        self,
        connection: sqlite3.Connection,
        version_id: str,
        artifacts: IndexArtifacts,
    ) -> None:
        for table in ("symbol_chunks", "evidence_refs", "knowledge_edges", "paper_entities", "code_entities", "indexed_files"):
            connection.execute(f"DELETE FROM {table} WHERE index_version_id=?", (version_id,))
        connection.executemany(
            "INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(version_id, item.path, item.kind, item.content_hash, item.size_bytes, item.parse_status,
              item.entity_count, item.edge_count, item.chunk_count, _json(item.errors)) for item in artifacts.indexed_files],
        )
        connection.executemany(
            """INSERT INTO code_entities VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [(version_id, item.id, item.repo_id, item.entity_type, item.path, item.name, item.qualified_name,
              item.module_name, item.parent_id, item.start_line, item.end_line, item.signature, item.source_code,
              item.docstring, item.content_hash, _json(item.evidence_refs), _json(item.metadata))
             for item in artifacts.code_entities],
        )
        connection.executemany(
            """INSERT INTO paper_entities VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [(version_id, item.id, item.paper_id, item.entity_type, item.title, item.text, item.page_number,
              _json(item.bbox) if item.bbox else None, item.figure_path, _json(item.keywords),
              _json(item.module_names), item.content_hash, _json(item.evidence_refs), _json(item.metadata))
             for item in artifacts.paper_entities],
        )
        connection.executemany(
            """INSERT INTO knowledge_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(version_id, item.id, item.repo_id, item.source_id, item.target_id, item.edge_type, item.confidence,
              item.resolution_type, item.unresolved_symbol, _json(item.evidence_refs), _json(item.metadata))
             for item in artifacts.edges],
        )
        connection.executemany(
            """INSERT INTO evidence_refs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(version_id, item.id, item.source_type, item.entity_id, item.file_path, item.start_line, item.end_line,
              item.paper_id, item.page_number, item.figure_id, _json(item.bbox) if item.bbox else None,
              item.content_hash) for item in artifacts.evidence],
        )
        connection.executemany(
            """INSERT INTO symbol_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(version_id, item.id, item.repo_id, item.entity_id, item.entity_kind, item.chunk_type, item.path,
              item.page_number, item.start_line, item.end_line, item.ordinal, item.text, item.content_hash,
              item.char_count, _json(item.metadata)) for item in artifacts.chunks],
        )

    def _validate_artifacts(self, artifacts: IndexArtifacts) -> None:
        entity_ids = {item.id for item in artifacts.code_entities} | {item.id for item in artifacts.paper_entities}
        evidence_ids = {item.id for item in artifacts.evidence}
        for entity in artifacts.code_entities:
            if entity.parent_id and entity.parent_id not in entity_ids:
                raise ValueError(f"Code entity {entity.id} has missing parent {entity.parent_id}.")
            if any(ref not in evidence_ids for ref in entity.evidence_refs):
                raise ValueError(f"Code entity {entity.id} references missing evidence.")
        for entity in artifacts.paper_entities:
            if any(ref not in evidence_ids for ref in entity.evidence_refs):
                raise ValueError(f"Paper entity {entity.id} references missing evidence.")
        for edge in artifacts.edges:
            if edge.source_id not in entity_ids:
                raise ValueError(f"Edge {edge.id} has missing source {edge.source_id}.")
            if edge.target_id and edge.target_id not in entity_ids:
                raise ValueError(f"Edge {edge.id} has missing target {edge.target_id}.")
            if any(ref not in evidence_ids for ref in edge.evidence_refs):
                raise ValueError(f"Edge {edge.id} references missing evidence.")
        for chunk in artifacts.chunks:
            if chunk.entity_id not in entity_ids:
                raise ValueError(f"Chunk {chunk.id} has missing entity {chunk.entity_id}.")
        for item in artifacts.evidence:
            if item.entity_id and item.entity_id not in entity_ids:
                raise ValueError(f"Evidence {item.id} has missing entity {item.entity_id}.")

    def _validate_persisted_counts(
        self,
        connection: sqlite3.Connection,
        version_id: str,
        artifacts: IndexArtifacts,
    ) -> None:
        expected = {
            "indexed_files": len(artifacts.indexed_files),
            "code_entities": len(artifacts.code_entities),
            "paper_entities": len(artifacts.paper_entities),
            "knowledge_edges": len(artifacts.edges),
            "evidence_refs": len(artifacts.evidence),
            "symbol_chunks": len(artifacts.chunks),
        }
        for table, count in expected.items():
            actual = int(connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE index_version_id=?", (version_id,)
            ).fetchone()[0])
            if actual != count:
                raise ValueError(
                    f"Structured index activation count mismatch for {table}: expected {count}, got {actual}."
                )

    def _write(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        delay = 0.1
        for attempt in range(self.max_retries):
            try:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    result = operation(connection)
                    connection.commit()
                    return result
            except sqlite3.OperationalError as exc:
                if not _is_retryable_sqlite_error(exc) or attempt + 1 >= self.max_retries:
                    raise
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("Unreachable SQLite retry state.")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
        return connection


def _version_id(repo_id: str, sequence: int, input_hash: str) -> str:
    digest = hashlib.sha256(f"{repo_id}\0{sequence}\0{input_hash}".encode("utf-8")).hexdigest()
    return f"idx_{digest}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lease_expiry(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _lease_expired(value: str | None) -> bool:
    if not value:
        return True
    try:
        return datetime.fromisoformat(value) <= datetime.now(UTC)
    except ValueError:
        return True


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_retryable_sqlite_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in ("locked", "busy", "temporarily unavailable", "disk i/o error"))
