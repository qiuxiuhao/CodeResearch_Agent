from __future__ import annotations

import pytest

from backend.app.retrieval.fusion import final_rrf, preliminary_rrf
from backend.app.retrieval.schemas import RawRetrievalHit, RetrievalConfig


def _config() -> RetrievalConfig:
    return RetrievalConfig(profile="symbol_lookup")


def test_preliminary_rrf_only_combines_dense_and_sparse() -> None:
    dense = [RawRetrievalHit(
        source="dense", chunk_id="chunk-a", entity_id="entity-a", source_score=0.8, source_rank=1
    )]
    sparse = [RawRetrievalHit(
        source="sparse", chunk_id="chunk-a", entity_id="entity-a", source_score=20.0, source_rank=2
    )]
    candidate = preliminary_rrf(dense, sparse, _config())[0]
    assert candidate.preliminary_rrf is not None
    assert candidate.final_rrf is None
    graph = RawRetrievalHit(
        source="graph", chunk_id="chunk-b", entity_id="entity-b", source_score=0.2, source_rank=1
    )
    with pytest.raises(ValueError):
        preliminary_rrf(dense, [graph], _config())


def test_final_rrf_preserves_all_source_contributions() -> None:
    dense = [RawRetrievalHit(
        source="dense", chunk_id="chunk-a", entity_id="entity-a", source_score=0.8, source_rank=1
    )]
    sparse = [RawRetrievalHit(
        source="sparse", chunk_id="chunk-a", entity_id="entity-a", source_score=20.0, source_rank=1,
        metadata={"exact_boost": 10.0},
    )]
    graph = [RawRetrievalHit(
        source="graph", chunk_id="chunk-a", entity_id="entity-a", source_score=0.2, source_rank=1,
        metadata={"graph_path_edge_ids": ["edge-1"]},
    )]
    candidate = final_rrf(dense, sparse, graph, _config())[0]
    assert candidate.preliminary_rrf is None
    assert candidate.final_rrf is not None
    assert set(candidate.contributions) == {"dense", "sparse", "graph", "exact_match_boost"}
    assert candidate.graph_path_edge_ids == ["edge-1"]


def test_raw_scores_are_not_compared_across_sources() -> None:
    config = _config()
    high_raw_low_rank = RawRetrievalHit(
        source="sparse", chunk_id="chunk-low-rank", entity_id="entity-1", source_score=1_000_000, source_rank=20
    )
    low_raw_high_rank = RawRetrievalHit(
        source="dense", chunk_id="chunk-high-rank", entity_id="entity-2", source_score=0.01, source_rank=1
    )
    result = preliminary_rrf([low_raw_high_rank], [high_raw_low_rank], config)
    assert result[0].chunk_id == "chunk-high-rank"
