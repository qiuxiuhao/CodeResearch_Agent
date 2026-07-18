from __future__ import annotations

from backend.app.retrieval.reranker import MockReranker, fuse_reranker
from backend.app.retrieval.schemas import FusedRetrievalCandidate, RawRetrievalHit, RetrievalConfig


def _candidate(chunk_id: str, score: float, *, exact: bool = False):
    return FusedRetrievalCandidate(
        chunk_id=chunk_id,
        entity_id=f"entity-{chunk_id}",
        hits=[RawRetrievalHit(
            source="sparse", chunk_id=chunk_id, entity_id=f"entity-{chunk_id}", source_score=1.0, source_rank=1
        )],
        final_rrf=score,
        contributions={"exact_match_boost": 0.05} if exact else {},
    )


def _config() -> RetrievalConfig:
    return RetrievalConfig(
        profile="symbol_lookup", reranker_enabled=True,
        hybrid_weight=0.7, reranker_weight=0.3,
    )


def test_exact_symbol_survives_bad_reranker_score() -> None:
    exact = _candidate("exact", 1.0, exact=True)
    other = _candidate("other", 0.5)
    result, warnings = fuse_reranker(
        query_text="symbol", candidates=[exact, other], config=_config(),
        reranker=MockReranker({"exact": 0.0, "other": 1.0}),
    )
    assert not warnings
    assert result[0].candidate.chunk_id == "exact"


def test_reranker_and_rrf_contributions_are_explained() -> None:
    result, _ = fuse_reranker(
        query_text="symbol", candidates=[_candidate("a", 1.0), _candidate("b", 0.5)],
        config=_config(), reranker=MockReranker({"a": 0.2, "b": 0.8}),
    )
    assert result[0].reranker_score is not None
    assert result[0].reranker_normalized is not None
    assert {"hybrid_final_rrf", "reranker"}.issubset(result[0].contributions)


def test_reranker_failure_preserves_final_rrf_order() -> None:
    candidates = [_candidate("a", 1.0), _candidate("b", 0.5)]
    result, warnings = fuse_reranker(
        query_text="symbol", candidates=candidates, config=_config(),
        reranker=MockReranker({}, error=RuntimeError("offline")),
    )
    assert [item.candidate.chunk_id for item in result] == ["a", "b"]
    assert warnings == ["reranker_failed_fallback_to_final_rrf"]
