from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.persistence.retrieval_read_store import RetrievalReadStore


@dataclass(frozen=True)
class AlignmentFacts:
    repo_id: str
    index_version_id: str
    paper_id: str
    code_entities: list[CodeEntity]
    paper_entities: list[PaperEntity]
    edges: list[KnowledgeEdge]
    chunks_by_entity: dict[str, list[SymbolChunk]]


class AlignmentFactReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.version_reader = RetrievalReadStore(path)

    def resolve_version(self, repo_id: str, requested_version_id: str | None = None) -> str:
        return self.version_reader.resolve_version(repo_id, requested_version_id)

    def read(self, *, repo_id: str, index_version_id: str, paper_id: str) -> AlignmentFacts:
        self.resolve_version(repo_id, index_version_id)
        with self._connect() as connection:
            code_rows = connection.execute(
                "SELECT * FROM code_entities WHERE repo_id=? AND index_version_id=? ORDER BY entity_id",
                (repo_id, index_version_id),
            ).fetchall()
            paper_rows = connection.execute(
                "SELECT * FROM paper_entities WHERE index_version_id=? AND paper_id=? ORDER BY entity_id",
                (index_version_id, paper_id),
            ).fetchall()
            edge_rows = connection.execute(
                "SELECT * FROM knowledge_edges WHERE repo_id=? AND index_version_id=? ORDER BY edge_id",
                (repo_id, index_version_id),
            ).fetchall()
            chunk_rows = connection.execute(
                "SELECT * FROM symbol_chunks WHERE repo_id=? AND index_version_id=? ORDER BY entity_id,chunk_id",
                (repo_id, index_version_id),
            ).fetchall()
        if not paper_rows:
            raise ValueError(f"paper_not_found:{paper_id}")
        chunks: dict[str, list[SymbolChunk]] = {}
        for row in chunk_rows:
            item = SymbolChunk(
                id=row["chunk_id"], repo_id=row["repo_id"], entity_id=row["entity_id"],
                entity_kind=row["entity_kind"], chunk_type=row["chunk_type"], path=row["path"],
                page_number=row["page_number"], start_line=row["start_line"], end_line=row["end_line"],
                ordinal=row["ordinal"], text=row["text"], content_hash=row["content_hash"],
                char_count=row["char_count"], metadata=_loads(row["metadata_json"], {}),
            )
            chunks.setdefault(item.entity_id, []).append(item)
        return AlignmentFacts(
            repo_id=repo_id,
            index_version_id=index_version_id,
            paper_id=paper_id,
            code_entities=[_code_entity(row) for row in code_rows],
            paper_entities=[_paper_entity(row) for row in paper_rows],
            edges=[_edge(row) for row in edge_rows],
            chunks_by_entity=chunks,
        )


    def input_payload(self, *, repo_id: str, index_version_id: str, paper_id: str) -> dict:
        facts = self.read(repo_id=repo_id, index_version_id=index_version_id, paper_id=paper_id)
        return {
            "repo_id": repo_id,
            "index_version_id": index_version_id,
            "paper_id": paper_id,
            "code_entities": [(item.id, item.content_hash) for item in facts.code_entities],
            "paper_entities": [(item.id, item.content_hash) for item in facts.paper_entities],
            "edges": [(item.id, item.edge_type, item.confidence) for item in facts.edges],
        }


    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection


def _code_entity(row: sqlite3.Row) -> CodeEntity:
    return CodeEntity(
        id=row["entity_id"], repo_id=row["repo_id"], entity_type=row["entity_type"], path=row["path"],
        name=row["name"], qualified_name=row["qualified_name"], module_name=row["module_name"],
        parent_id=row["parent_id"], start_line=row["start_line"], end_line=row["end_line"],
        signature=row["signature"], source_code=row["source_code"], docstring=row["docstring"],
        content_hash=row["content_hash"], evidence_refs=_loads(row["evidence_refs_json"], []),
        metadata=_loads(row["metadata_json"], {}),
    )


def _paper_entity(row: sqlite3.Row) -> PaperEntity:
    bbox = _loads(row["bbox_json"], None)
    return PaperEntity(
        id=row["entity_id"], paper_id=row["paper_id"], entity_type=row["entity_type"], title=row["title"],
        text=row["text"], page_number=row["page_number"], bbox=tuple(bbox) if bbox else None,
        figure_path=row["figure_path"], keywords=_loads(row["keywords_json"], []),
        module_names=_loads(row["module_names_json"], []), content_hash=row["content_hash"],
        evidence_refs=_loads(row["evidence_refs_json"], []), metadata=_loads(row["metadata_json"], {}),
    )


def _edge(row: sqlite3.Row) -> KnowledgeEdge:
    return KnowledgeEdge(
        id=row["edge_id"], repo_id=row["repo_id"], source_id=row["source_id"], target_id=row["target_id"],
        edge_type=row["edge_type"], confidence=row["confidence"], resolution_type=row["resolution_type"],
        unresolved_symbol=row["unresolved_symbol"], evidence_refs=_loads(row["evidence_refs_json"], []),
        metadata=_loads(row["metadata_json"], {}),
    )


def _loads(value: str | None, default):
    return json.loads(value) if value else default
