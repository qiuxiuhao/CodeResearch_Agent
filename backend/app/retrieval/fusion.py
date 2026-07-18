from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from backend.app.retrieval.schemas import FusedRetrievalCandidate, RawRetrievalHit, RetrievalConfig


EXACT_MATCH_RRF_BOOST = 0.05


def preliminary_rrf(
    raw_dense_hits: Sequence[RawRetrievalHit],
    raw_sparse_hits: Sequence[RawRetrievalHit],
    config: RetrievalConfig,
) -> list[FusedRetrievalCandidate]:
    hits = [*raw_dense_hits, *raw_sparse_hits]
    if any(hit.source == "graph" for hit in hits):
        raise ValueError("Preliminary RRF accepts only dense and sparse hits.")
    return _fuse(hits, config, preliminary=True)


def final_rrf(
    raw_dense_hits: Sequence[RawRetrievalHit],
    raw_sparse_hits: Sequence[RawRetrievalHit],
    graph_candidates: Sequence[RawRetrievalHit],
    config: RetrievalConfig,
) -> list[FusedRetrievalCandidate]:
    return _fuse([*raw_dense_hits, *raw_sparse_hits, *graph_candidates], config, preliminary=False)


def _fuse(
    hits: Sequence[RawRetrievalHit], config: RetrievalConfig, *, preliminary: bool
) -> list[FusedRetrievalCandidate]:
    grouped: dict[str, list[RawRetrievalHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.chunk_id].append(hit)
    candidates: list[FusedRetrievalCandidate] = []
    for chunk_id, chunk_hits in grouped.items():
        contributions: dict[str, float] = {}
        score = 0.0
        exact = False
        for hit in chunk_hits:
            contribution = config.source_weights.get(hit.source, 1.0) / (config.rrf_k + hit.source_rank)
            contributions[hit.source] = contributions.get(hit.source, 0.0) + contribution
            score += contribution
            exact = exact or float(hit.metadata.get("exact_boost", 0.0)) > 0
        if exact:
            score += EXACT_MATCH_RRF_BOOST
            contributions["exact_match_boost"] = EXACT_MATCH_RRF_BOOST
        candidate = FusedRetrievalCandidate(
            chunk_id=chunk_id,
            entity_id=min(hit.entity_id for hit in chunk_hits),
            hits=sorted(chunk_hits, key=lambda hit: (hit.source, hit.source_rank, hit.chunk_id)),
            preliminary_rrf=score if preliminary else None,
            final_rrf=None if preliminary else score,
            graph_path_edge_ids=_graph_path(chunk_hits),
            contributions=contributions,
        )
        candidates.append(candidate)
    return sorted(
        candidates,
        key=lambda candidate: (
            -(candidate.preliminary_rrf if preliminary else candidate.final_rrf or 0.0),
            -candidate.contributions.get("exact_match_boost", 0.0),
            min(hit.source_rank for hit in candidate.hits),
            candidate.entity_id,
            candidate.chunk_id,
        ),
    )[: config.fusion_top_k]


def _graph_path(hits: Sequence[RawRetrievalHit]) -> list[str]:
    paths = [list(hit.metadata.get("graph_path_edge_ids", [])) for hit in hits if hit.source == "graph"]
    return min(paths, key=lambda path: (len(path), path)) if paths else []
