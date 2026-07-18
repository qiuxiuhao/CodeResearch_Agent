from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.persistence.migration_runner import migrate_database
from backend.app.retrieval.schemas import RetrievalDocument, RetrievalEvidence, RetrievalFilter


class RetrievalReadError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class RetrievalReadStore:
    """Read-only retrieval boundary over immutable structured-index versions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def resolve_version(self, repo_id: str, requested_version_id: str | None = None) -> str:
        migrate_database(self.path)
        with self._connect() as connection:
            repository = connection.execute(
                "SELECT active_version_id FROM repositories WHERE repo_id=?", (repo_id,)
            ).fetchone()
            if repository is None:
                raise RetrievalReadError("repository_not_found", f"Repository {repo_id} was not found.")
            version_id = requested_version_id or repository["active_version_id"]
            if not version_id:
                raise RetrievalReadError("index_version_not_active", f"Repository {repo_id} has no active index.")
            version = connection.execute(
                "SELECT status FROM index_versions WHERE repo_id=? AND index_version_id=?",
                (repo_id, version_id),
            ).fetchone()
        if version is None:
            raise RetrievalReadError(
                "index_version_not_found", f"Index version {version_id} does not belong to repository {repo_id}."
            )
        if version["status"] not in {"active", "superseded"}:
            raise RetrievalReadError(
                "index_version_not_active", f"Index version {version_id} is not readable: {version['status']}."
            )
        return str(version_id)

    def list_documents(self, filters: RetrievalFilter) -> list[RetrievalDocument]:
        self.resolve_version(filters.repo_id, filters.index_version_id)
        clauses = ["c.repo_id=?", "c.index_version_id=?"]
        parameters: list[object] = [filters.repo_id, filters.index_version_id]
        self._append_in_filter(clauses, parameters, "COALESCE(ce.entity_type, pe.entity_type)", filters.entity_types)
        self._append_in_filter(clauses, parameters, "c.entity_kind", filters.entity_kinds)
        self._append_in_filter(clauses, parameters, "c.path", filters.paths)
        self._append_in_filter(clauses, parameters, "ce.qualified_name", filters.qualified_names)
        self._append_in_filter(clauses, parameters, "c.chunk_type", filters.chunk_types)
        if filters.path_prefixes:
            clauses.append("(" + " OR ".join("c.path LIKE ? ESCAPE '\\'" for _ in filters.path_prefixes) + ")")
            parameters.extend(_like_prefix(item) for item in filters.path_prefixes)
        query = f"""
            SELECT c.*, COALESCE(ce.entity_type, pe.entity_type) AS resolved_entity_type,
                   COALESCE(ce.qualified_name, pe.title) AS resolved_qualified_name,
                   ce.parent_id AS resolved_parent_id
            FROM symbol_chunks c
            LEFT JOIN code_entities ce
              ON ce.index_version_id=c.index_version_id AND ce.entity_id=c.entity_id
            LEFT JOIN paper_entities pe
              ON pe.index_version_id=c.index_version_id AND pe.entity_id=c.entity_id
            WHERE {' AND '.join(clauses)}
            ORDER BY c.chunk_id
        """
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._document(row) for row in rows]

    def documents_by_chunk_ids(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        chunk_ids: Sequence[str],
    ) -> dict[str, RetrievalDocument]:
        if not chunk_ids:
            return {}
        filters = RetrievalFilter(repo_id=repo_id, index_version_id=index_version_id)
        documents = self.list_documents(filters)
        requested = set(chunk_ids)
        return {item.chunk_id: item for item in documents if item.chunk_id in requested}

    def chunks_for_entities(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        entity_ids: Sequence[str],
    ) -> dict[str, list[SymbolChunk]]:
        if not entity_ids:
            return {}
        self.resolve_version(repo_id, index_version_id)
        placeholders = ",".join("?" for _ in entity_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM symbol_chunks
                    WHERE repo_id=? AND index_version_id=? AND entity_id IN ({placeholders})
                    ORDER BY entity_id, chunk_id""",
                [repo_id, index_version_id, *entity_ids],
            ).fetchall()
        result: dict[str, list[SymbolChunk]] = {}
        for row in rows:
            chunk = SymbolChunk(
                id=row["chunk_id"], repo_id=row["repo_id"], entity_id=row["entity_id"],
                entity_kind=row["entity_kind"], chunk_type=row["chunk_type"], path=row["path"],
                page_number=row["page_number"], start_line=row["start_line"], end_line=row["end_line"],
                ordinal=row["ordinal"], text=row["text"], content_hash=row["content_hash"],
                char_count=row["char_count"], metadata=_loads(row["metadata_json"], {}),
            )
            result.setdefault(chunk.entity_id, []).append(chunk)
        return result

    def evidence_for_entities(
        self,
        *,
        index_version_id: str,
        entity_ids: Sequence[str],
    ) -> dict[str, list[RetrievalEvidence]]:
        if not entity_ids:
            return {}
        placeholders = ",".join("?" for _ in entity_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM evidence_refs
                    WHERE index_version_id=? AND entity_id IN ({placeholders})
                    ORDER BY entity_id, evidence_id""",
                [index_version_id, *entity_ids],
            ).fetchall()
        result: dict[str, list[RetrievalEvidence]] = {}
        for row in rows:
            evidence = RetrievalEvidence(
                evidence_id=row["evidence_id"], source_type=row["source_type"], path=row["file_path"],
                start_line=row["start_line"], end_line=row["end_line"], paper_id=row["paper_id"],
                page_number=row["page_number"], figure_id=row["figure_id"],
                bbox=_tuple_or_none(row["bbox_json"]),
            )
            result.setdefault(str(row["entity_id"]), []).append(evidence)
        return result

    def graph_neighbors(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        entity_ids: Sequence[str],
        edge_types: Sequence[str],
        include_incoming: bool = True,
    ) -> list[KnowledgeEdge]:
        if not entity_ids or not edge_types:
            return []
        self.resolve_version(repo_id, index_version_id)
        entity_placeholders = ",".join("?" for _ in entity_ids)
        type_placeholders = ",".join("?" for _ in edge_types)
        direction = f"source_id IN ({entity_placeholders})"
        parameters: list[object] = [*entity_ids]
        if include_incoming:
            direction = f"({direction} OR target_id IN ({entity_placeholders}))"
            parameters.extend(entity_ids)
        parameters = [index_version_id, repo_id, *parameters, *edge_types]
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM knowledge_edges
                    WHERE index_version_id=? AND repo_id=? AND {direction}
                      AND edge_type IN ({type_placeholders})
                    ORDER BY confidence DESC, edge_id""",
                parameters,
            ).fetchall()
        return [
            KnowledgeEdge(
                id=row["edge_id"], repo_id=row["repo_id"], source_id=row["source_id"],
                target_id=row["target_id"], edge_type=row["edge_type"], confidence=row["confidence"],
                resolution_type=row["resolution_type"], unresolved_symbol=row["unresolved_symbol"],
                evidence_refs=_loads(row["evidence_refs_json"], []),
                metadata=_loads(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _append_in_filter(
        clauses: list[str], parameters: list[object], column: str, values: Iterable[str]
    ) -> None:
        values = list(values)
        if values:
            clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
            parameters.extend(values)

    @staticmethod
    def _document(row: sqlite3.Row) -> RetrievalDocument:
        return RetrievalDocument(
            chunk_id=row["chunk_id"], entity_id=row["entity_id"], repo_id=row["repo_id"],
            index_version_id=row["index_version_id"], entity_kind=row["entity_kind"],
            entity_type=row["resolved_entity_type"], chunk_type=row["chunk_type"], path=row["path"],
            qualified_name=row["resolved_qualified_name"], parent_entity_id=row["resolved_parent_id"],
            start_line=row["start_line"], end_line=row["end_line"], page_number=row["page_number"],
            ordinal=row["ordinal"], text=row["text"], content_hash=row["content_hash"],
            metadata=_loads(row["metadata_json"], {}),
        )


def _loads(value: str | None, default: object):
    if not value:
        return default
    return json.loads(value)


def _tuple_or_none(value: str | None) -> tuple[float, float, float, float] | None:
    parsed = _loads(value, None)
    return tuple(parsed) if parsed is not None else None


def _like_prefix(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"
