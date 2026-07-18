from __future__ import annotations

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.persistence.index_store import IndexArtifacts, StructuredIndexStore
from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.retrieval.schemas import RetrievalFilter


def _build_index(path) -> tuple[str, str]:
    store = StructuredIndexStore(path)
    lease = store.begin_version(
        repo_id="repo_test", identity_mode="explicit", repository_key="test/repo",
        display_name="repo", input_hash="input-1",
    )
    evidence = EvidenceRef(
        id="ev-1", source_type="code", entity_id="entity-1", file_path="model.py",
        start_line=1, end_line=2,
    )
    entity = CodeEntity(
        id="entity-1", repo_id="repo_test", entity_type="function", path="model.py",
        name="forward", qualified_name="model.forward", start_line=1, end_line=2,
        source_code="def forward(x):\n    return x", content_hash="hash-1", evidence_refs=["ev-1"],
    )
    chunk = SymbolChunk(
        id="chunk-1", repo_id="repo_test", entity_id="entity-1", entity_kind="code",
        chunk_type="function", path="model.py", start_line=1, end_line=2,
        text="def forward(x):\n    return x", content_hash="hash-1", char_count=28,
    )
    edge = KnowledgeEdge(
        id="edge-1", repo_id="repo_test", source_id="entity-1", target_id=None,
        edge_type="CALLS", confidence=0.5, resolution_type="unresolved", unresolved_symbol="dynamic_call",
        evidence_refs=["ev-1"],
    )
    store.mark_ready(lease)
    store.activate(lease, IndexArtifacts([], [entity], [], [edge], [evidence], [chunk]))
    return lease.index_version_id, entity.id


def test_read_store_resolves_and_filters_active_snapshot(tmp_path) -> None:
    db_path = tmp_path / "index.sqlite3"
    version_id, _ = _build_index(db_path)
    store = RetrievalReadStore(db_path)
    assert store.resolve_version("repo_test") == version_id
    documents = store.list_documents(RetrievalFilter(
        repo_id="repo_test", index_version_id=version_id,
        entity_types=["function"], qualified_names=["model.forward"],
    ))
    assert len(documents) == 1
    assert documents[0].chunk_id == "chunk-1"
    assert documents[0].qualified_name == "model.forward"
    evidence = store.evidence_for_entities(index_version_id=version_id, entity_ids=["entity-1"])
    assert evidence["entity-1"][0].path == "model.py"


def test_read_store_keeps_unresolved_edge_as_non_traversable_fact(tmp_path) -> None:
    db_path = tmp_path / "index.sqlite3"
    version_id, entity_id = _build_index(db_path)
    edges = RetrievalReadStore(db_path).graph_neighbors(
        repo_id="repo_test", index_version_id=version_id,
        entity_ids=[entity_id], edge_types=["CALLS"],
    )
    assert len(edges) == 1
    assert edges[0].target_id is None
    assert edges[0].unresolved_symbol == "dynamic_call"
