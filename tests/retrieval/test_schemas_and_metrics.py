from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.retrieval.metrics import evaluate_rankings
from backend.app.retrieval.schemas import (
    FinalRetrievalCandidate,
    FusedRetrievalCandidate,
    RawRetrievalHit,
    RetrievalConfig,
    RetrievalSearchRequest,
)


def test_public_request_does_not_accept_repository_identity() -> None:
    request = RetrievalSearchRequest(text="find SimpleNet.forward")
    assert "repo_id" not in request.model_dump()
    with pytest.raises(ValidationError):
        RetrievalSearchRequest.model_validate({"text": "x", "repo_id": "repo_x"})


def test_final_candidate_requires_final_rrf() -> None:
    candidate = FusedRetrievalCandidate(
        chunk_id="chunk-1",
        entity_id="entity-1",
        hits=[RawRetrievalHit(
            source="sparse", chunk_id="chunk-1", entity_id="entity-1", source_score=4.0, source_rank=1
        )],
        preliminary_rrf=1 / 61,
    )
    with pytest.raises(ValidationError):
        FinalRetrievalCandidate(candidate=candidate, final_score=1.0)


def test_retrieval_config_weights_must_be_normalized() -> None:
    with pytest.raises(ValidationError):
        RetrievalConfig(profile="symbol_lookup", hybrid_weight=0.7, reranker_weight=0.3)
    enabled = RetrievalConfig(
        profile="symbol_lookup", reranker_enabled=True, hybrid_weight=0.7, reranker_weight=0.3
    )
    assert enabled.hybrid_weight + enabled.reranker_weight == 1.0


def test_metrics_match_hand_calculation() -> None:
    result = evaluate_rankings(
        [["a", "b", "c"], ["x", "y"]],
        [{"b"}, {"x"}],
        graph_paths=[[[]], [["edge-1"]]],
        gold_graph_paths=[[], [["edge-1"]]],
        latencies_ms=[10.0, 30.0],
    )
    assert result.recall_at_1 == 0.5
    assert result.recall_at_5 == 1.0
    assert result.mrr == 0.75
    assert result.graph_path_recall == 1.0
    assert result.average_latency_ms == 20.0
