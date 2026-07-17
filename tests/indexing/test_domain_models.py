from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import IndexManifest, IndexedFile, SymbolChunk


def test_domain_models_round_trip_without_replacing_legacy_schemas() -> None:
    code = CodeEntity(
        id="code", repo_id="repo", entity_type="function", path="pkg/a.py", name="run",
        qualified_name="pkg.a.run", module_name="pkg.a", start_line=1, end_line=2,
        content_hash="code-hash", evidence_refs=["evidence"],
    )
    paper = PaperEntity(
        id="paper-entity", paper_id="paper", entity_type="contribution", title="Method",
        text="A contribution", page_number=1, content_hash="paper-hash", evidence_refs=["paper-evidence"],
    )
    evidence = EvidenceRef(
        id="evidence", source_type="code", entity_id="code", file_path="pkg/a.py", start_line=1, end_line=2,
    )
    edge = KnowledgeEdge(
        id="edge", repo_id="repo", source_id="code", target_id="paper-entity",
        edge_type="ALIGNS_WITH", confidence=0.9, resolution_type="exact", evidence_refs=["evidence"],
    )
    chunk = SymbolChunk(
        id="chunk", repo_id="repo", entity_id="code", entity_kind="code", chunk_type="function",
        path="pkg/a.py", ordinal=0, text="def run(): pass", content_hash="chunk-hash", char_count=15,
    )
    indexed = IndexedFile(
        path="pkg/a.py", kind="python", content_hash="file-hash", size_bytes=15, parse_status="success",
        entity_count=1, edge_count=1, chunk_count=1,
    )
    manifest = IndexManifest(
        manifest_version="1.4.0", index_schema_version="1.4.0", repo_id="repo",
        repository_identity_mode="explicit", index_version_id="version", index_sequence=1,
        input_hash="input", status="active", builder_versions={"code_entity": "1"}, file_count=1,
        code_entity_count=1, paper_entity_count=1, edge_count=1, evidence_count=1, chunk_count=1,
        unresolved_call_count=0, ambiguous_call_count=0, created_at=datetime.now(UTC),
    )

    for value in (code, paper, evidence, edge, chunk, indexed, manifest):
        assert type(value).model_validate(value.model_dump(mode="json")) == value


def test_targetless_edge_must_retain_unresolved_symbol() -> None:
    with pytest.raises(ValidationError):
        KnowledgeEdge(
            id="edge", repo_id="repo", source_id="source", edge_type="CALLS",
            confidence=0.2, resolution_type="unresolved",
        )

