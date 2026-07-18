from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from backend.app.retrieval.schemas import RawRetrievalHit, RetrievalDocument, RetrievalFilter


FTS_PROFILE_VERSION = "fts5-unicode61-symbol-v1"


class FTSGenerationError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class FTSGenerationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS retrieval_fts_generations (
                    generation_id TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    index_version_id TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('building','ready','stale','failed','superseded')),
                    document_count INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    error_code TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_fts_ready_scope
                  ON retrieval_fts_generations(repo_id, index_version_id, profile_hash)
                  WHERE status='ready';
                CREATE INDEX IF NOT EXISTS idx_fts_generation_scope
                  ON retrieval_fts_generations(repo_id, index_version_id, profile_hash, status);

                CREATE TABLE IF NOT EXISTS retrieval_documents (
                    document_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_id TEXT NOT NULL REFERENCES retrieval_fts_generations(generation_id) ON DELETE CASCADE,
                    chunk_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    entity_kind TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    path TEXT,
                    qualified_name TEXT,
                    parent_entity_id TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    page_number INTEGER,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(generation_id, chunk_id)
                );
                CREATE INDEX IF NOT EXISTS idx_fts_documents_scope
                  ON retrieval_documents(generation_id, entity_type, path, qualified_name);
                CREATE VIRTUAL TABLE IF NOT EXISTS retrieval_documents_fts USING fts5(
                    text, symbol_text, path_text, tokenize='unicode61'
                );
                """
            )

    def sync(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        profile_hash: str,
        documents: Sequence[RetrievalDocument],
        fail_before_activation: bool = False,
    ) -> tuple[str, bool]:
        self.ensure_schema()
        content_hash = _documents_hash(documents)
        generation_id = _generation_id(repo_id, index_version_id, profile_hash, content_hash)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT status FROM retrieval_fts_generations WHERE generation_id=?", (generation_id,)
            ).fetchone()
            if existing is not None and existing["status"] == "ready":
                return generation_id, True
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO retrieval_fts_generations(
                       generation_id, repo_id, index_version_id, profile_hash, status,
                       document_count, content_hash, created_at, activated_at, error_code
                   ) VALUES (?, ?, ?, ?, 'building', 0, ?, ?, NULL, NULL)
                   ON CONFLICT(generation_id) DO UPDATE SET
                       status='building', document_count=0, activated_at=NULL, error_code=NULL""",
                (generation_id, repo_id, index_version_id, profile_hash, content_hash, _now()),
            )
            self._delete_generation_documents(connection, generation_id)
            connection.commit()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for document in sorted(documents, key=lambda item: item.chunk_id):
                    cursor = connection.execute(
                        """INSERT INTO retrieval_documents(
                               generation_id, chunk_id, entity_id, entity_kind, entity_type, chunk_type,
                               path, qualified_name, parent_entity_id, start_line, end_line, page_number,
                               ordinal, text, content_hash, metadata_json
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            generation_id, document.chunk_id, document.entity_id, document.entity_kind,
                            document.entity_type, document.chunk_type, document.path, document.qualified_name,
                            document.parent_entity_id, document.start_line, document.end_line,
                            document.page_number, document.ordinal, document.text, document.content_hash,
                            _json(document.metadata),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO retrieval_documents_fts(rowid, text, symbol_text, path_text) VALUES (?, ?, ?, ?)",
                        (
                            cursor.lastrowid, document.text,
                            _symbol_text(document.qualified_name, document.text),
                            _symbol_text(document.path, ""),
                        ),
                    )
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM retrieval_documents WHERE generation_id=?", (generation_id,)
                ).fetchone()[0])
                if count != len(documents):
                    raise FTSGenerationError("fts_count_mismatch", "FTS generation document count mismatch.")
                if fail_before_activation:
                    raise FTSGenerationError("fts_sync_injected_failure", "Injected FTS activation failure.")
                connection.execute(
                    """UPDATE retrieval_fts_generations SET status='superseded'
                       WHERE repo_id=? AND index_version_id=? AND profile_hash=?
                         AND status='ready' AND generation_id<>?""",
                    (repo_id, index_version_id, profile_hash, generation_id),
                )
                connection.execute(
                    """UPDATE retrieval_fts_generations
                       SET status='ready', document_count=?, activated_at=?, error_code=NULL
                       WHERE generation_id=? AND status='building'""",
                    (count, _now(), generation_id),
                )
                connection.commit()
        except Exception as exc:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._delete_generation_documents(connection, generation_id)
                connection.execute(
                    "UPDATE retrieval_fts_generations SET status='failed', error_code=? WHERE generation_id=?",
                    (getattr(exc, "error_code", "fts_sync_failed"), generation_id),
                )
                connection.commit()
            raise
        return generation_id, False

    def search(
        self,
        *,
        query_text: str,
        filters: RetrievalFilter,
        profile_hash: str,
        top_k: int,
    ) -> list[RawRetrievalHit]:
        self.ensure_schema()
        expression = _match_expression(query_text)
        if not expression:
            return []
        generation = self.ready_generation(
            repo_id=filters.repo_id,
            index_version_id=filters.index_version_id,
            profile_hash=profile_hash,
        )
        if generation is None:
            raise FTSGenerationError("fts_generation_not_ready", "No ready FTS generation exists.")
        clauses = ["d.generation_id=?", "retrieval_documents_fts MATCH ?"]
        parameters: list[object] = [generation["generation_id"], expression]
        _append_filter(clauses, parameters, "d.entity_type", filters.entity_types)
        _append_filter(clauses, parameters, "d.entity_kind", filters.entity_kinds)
        _append_filter(clauses, parameters, "d.path", filters.paths)
        _append_filter(clauses, parameters, "d.qualified_name", filters.qualified_names)
        _append_filter(clauses, parameters, "d.chunk_type", filters.chunk_types)
        if filters.path_prefixes:
            clauses.append("(" + " OR ".join("d.path LIKE ? ESCAPE '\\'" for _ in filters.path_prefixes) + ")")
            parameters.extend(_like_prefix(item) for item in filters.path_prefixes)
        query = f"""
            SELECT d.*, bm25(retrieval_documents_fts, 1.0, 2.5, 1.5) AS bm25_score
            FROM retrieval_documents_fts
            JOIN retrieval_documents d ON d.document_id=retrieval_documents_fts.rowid
            WHERE {' AND '.join(clauses)}
        """
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        normalized_query = query_text.strip().casefold()
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            boost = _exact_boost(normalized_query, row["qualified_name"], row["path"])
            ranked.append((-float(row["bm25_score"]) + boost, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [
            RawRetrievalHit(
                source="sparse", chunk_id=row["chunk_id"], entity_id=row["entity_id"],
                source_score=score, source_rank=rank,
                metadata={"generation_id": generation["generation_id"], "exact_boost": _exact_boost(
                    normalized_query, row["qualified_name"], row["path"]
                )},
            )
            for rank, (score, row) in enumerate(ranked[:top_k], 1)
        ]

    def ready_generation(self, *, repo_id: str, index_version_id: str, profile_hash: str) -> dict | None:
        self.ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM retrieval_fts_generations
                   WHERE repo_id=? AND index_version_id=? AND profile_hash=? AND status='ready'""",
                (repo_id, index_version_id, profile_hash),
            ).fetchone()
        return dict(row) if row else None

    def generation_row(self, generation_id: str) -> dict | None:
        self.ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM retrieval_fts_generations WHERE generation_id=?", (generation_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_version(self, *, repo_id: str, index_version_id: str) -> None:
        self.ensure_schema()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            generations = connection.execute(
                "SELECT generation_id FROM retrieval_fts_generations WHERE repo_id=? AND index_version_id=?",
                (repo_id, index_version_id),
            ).fetchall()
            for row in generations:
                self._delete_generation_documents(connection, row["generation_id"])
            connection.execute(
                "DELETE FROM retrieval_fts_generations WHERE repo_id=? AND index_version_id=?",
                (repo_id, index_version_id),
            )
            connection.commit()

    @staticmethod
    def _delete_generation_documents(connection: sqlite3.Connection, generation_id: str) -> None:
        rows = connection.execute(
            "SELECT document_id FROM retrieval_documents WHERE generation_id=?", (generation_id,)
        ).fetchall()
        connection.executemany(
            "DELETE FROM retrieval_documents_fts WHERE rowid=?", [(row["document_id"],) for row in rows]
        )
        connection.execute("DELETE FROM retrieval_documents WHERE generation_id=?", (generation_id,))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _documents_hash(documents: Sequence[RetrievalDocument]) -> str:
    payload = [
        {"chunk_id": item.chunk_id, "content_hash": item.content_hash}
        for item in sorted(documents, key=lambda document: document.chunk_id)
    ]
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _generation_id(repo_id: str, index_version_id: str, profile_hash: str, content_hash: str) -> str:
    value = f"fts:v1\0{repo_id}\0{index_version_id}\0{profile_hash}\0{content_hash}"
    return "fts_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _symbol_text(primary: str | None, secondary: str) -> str:
    value = " ".join(part for part in (primary or "", secondary) if part)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return re.sub(r"[\\/._:\-]+", " ", value)


def _match_expression(query_text: str) -> str:
    terms = []
    for term in re.findall(r"[\w\u3400-\u9fff]+", _symbol_text(query_text, ""), flags=re.UNICODE):
        escaped = term.replace('"', '""')
        if escaped and escaped.casefold() not in {item.casefold() for item in terms}:
            terms.append(escaped)
    return " OR ".join(f'"{term}"' for term in terms[:32])


def _exact_boost(query: str, qualified_name: str | None, path: str | None) -> float:
    values = [item.casefold() for item in (qualified_name, path) if item]
    if query in values:
        return 10.0
    if any(query and query in item for item in values):
        return 2.0
    return 0.0


def _append_filter(clauses: list[str], parameters: list[object], column: str, values: Sequence[str]) -> None:
    if values:
        clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
        parameters.extend(values)


def _like_prefix(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()
