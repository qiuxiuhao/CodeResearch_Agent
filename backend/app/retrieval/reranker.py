from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.app.retrieval.schemas import (
    FinalRetrievalCandidate,
    FusedRetrievalCandidate,
    RetrievalConfig,
)


class Reranker(Protocol):
    def score(self, query_text: str, candidates: Sequence[FusedRetrievalCandidate]) -> Mapping[str, float]: ...


class IdentityReranker:
    def score(self, query_text: str, candidates: Sequence[FusedRetrievalCandidate]) -> Mapping[str, float]:
        return {}


@dataclass(slots=True)
class MockReranker:
    scores: Mapping[str, float]
    error: Exception | None = None

    def score(self, query_text: str, candidates: Sequence[FusedRetrievalCandidate]) -> Mapping[str, float]:
        if self.error is not None:
            raise self.error
        return {candidate.chunk_id: float(self.scores[candidate.chunk_id]) for candidate in candidates if candidate.chunk_id in self.scores}


class FastEmbedCrossEncoderReranker:
    def __init__(self, *, model_id: str, cache_dir: str, offline: bool = True) -> None:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:
            raise RuntimeError("Install the optional 'retrieval' dependencies to use a reranker.") from exc
        self._model = TextCrossEncoder(model_name=model_id, cache_dir=cache_dir, local_files_only=offline)

    def score(self, query_text: str, candidates: Sequence[FusedRetrievalCandidate]) -> Mapping[str, float]:
        # The actual candidate text is supplied by the service through metadata.
        texts = [str(_candidate_text(candidate)) for candidate in candidates]
        values = list(self._model.rerank(query_text, texts))
        return {candidate.chunk_id: float(score) for candidate, score in zip(candidates, values, strict=True)}


def fuse_reranker(
    *,
    query_text: str,
    candidates: Sequence[FusedRetrievalCandidate],
    config: RetrievalConfig,
    reranker: Reranker | None,
) -> tuple[list[FinalRetrievalCandidate], list[str]]:
    warnings: list[str] = []
    rrf_values = {candidate.chunk_id: float(candidate.final_rrf or 0.0) for candidate in candidates}
    normalized_rrf = _normalize(rrf_values)
    reranker_values: Mapping[str, float] = {}
    if config.reranker_enabled and reranker is not None:
        try:
            reranker_values = reranker.score(query_text, candidates)
        except Exception:
            warnings.append("reranker_failed_fallback_to_final_rrf")
    elif config.reranker_enabled:
        warnings.append("reranker_unavailable_fallback_to_final_rrf")
    normalized_reranker = _normalize(dict(reranker_values)) if reranker_values else {}
    use_reranker = bool(normalized_reranker)
    hybrid_weight = config.hybrid_weight if use_reranker else 1.0
    reranker_weight = config.reranker_weight if use_reranker else 0.0
    result = []
    for candidate in candidates:
        hybrid_contribution = hybrid_weight * normalized_rrf[candidate.chunk_id]
        rerank_normalized = normalized_reranker.get(candidate.chunk_id)
        rerank_contribution = reranker_weight * (rerank_normalized or 0.0)
        contributions = {
            **candidate.contributions,
            "hybrid_final_rrf": hybrid_contribution,
            "reranker": rerank_contribution,
        }
        result.append(FinalRetrievalCandidate(
            candidate=candidate,
            reranker_score=float(reranker_values[candidate.chunk_id]) if candidate.chunk_id in reranker_values else None,
            reranker_normalized=rerank_normalized,
            final_score=hybrid_contribution + rerank_contribution,
            contributions=contributions,
        ))
    result.sort(key=lambda item: (
        -item.final_score,
        -item.contributions.get("exact_match_boost", 0.0),
        -(item.candidate.final_rrf or 0.0),
        item.candidate.entity_id,
        item.candidate.chunk_id,
    ))
    return result[: config.final_top_k], warnings


def _normalize(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {key: 1.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def _candidate_text(candidate: FusedRetrievalCandidate) -> str:
    for hit in candidate.hits:
        text = hit.metadata.get("text")
        if text:
            return str(text)
    return candidate.chunk_id
