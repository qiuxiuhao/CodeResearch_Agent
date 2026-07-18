from __future__ import annotations

from backend.app.domain.index_manifest import SymbolChunk
from backend.app.retrieval.entity_chunk_selector import EntityChunkSelector


def _chunk(chunk_id: str, chunk_type: str, start: int | None, end: int | None, text: str) -> SymbolChunk:
    return SymbolChunk(
        id=chunk_id, repo_id="repo", entity_id="entity", entity_kind="code",
        chunk_type=chunk_type, path="model.py", start_line=start, end_line=end,
        text=text, content_hash=f"hash-{chunk_id}", char_count=len(text),
    )


def test_graph_entity_selects_edge_evidence_chunk() -> None:
    selector = EntityChunkSelector(edge_evidence_lines={"edge-1": {42}})
    broad = _chunk("chunk-a", "file", 1, 100, "class Model: pass")
    exact = _chunk("chunk-z", "method", 40, 45, "def forward(self, x): return x")
    selected = selector.select(
        entity_id="entity", query_text="unrelated", query_profile="call_chain",
        graph_path_edge_ids=["edge-1"], available_chunks=[broad, exact],
    )
    assert selected == exact
    assert selector.last_rule == "graph_edge_evidence"


def test_graph_entity_selects_canonical_chunk_deterministically() -> None:
    selector = EntityChunkSelector()
    file_chunk = _chunk("chunk-a", "file", 1, 100, "file body")
    method_chunk = _chunk("chunk-z", "method", 10, 20, "method body")
    selected = selector.select(
        entity_id="entity", query_text="absent", query_profile="implementation_explanation",
        graph_path_edge_ids=[], available_chunks=[file_chunk, method_chunk],
    )
    assert selected == method_chunk
    assert selector.last_rule == "canonical_then_stable_id"


def test_graph_entity_without_chunk_becomes_note_only() -> None:
    selector = EntityChunkSelector()
    assert selector.select(
        entity_id="missing", query_text="x", query_profile="architecture",
        graph_path_edge_ids=["edge-1"], available_chunks=[],
    ) is None
    assert selector.last_rule == "note_only"
