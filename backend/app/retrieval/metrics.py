from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_5: float
    ndcg_at_10: float
    graph_path_recall: float
    average_latency_ms: float


def evaluate_rankings(
    rankings: Sequence[Sequence[str]],
    gold_ids: Sequence[set[str]],
    *,
    graph_paths: Sequence[Sequence[Sequence[str]]] | None = None,
    gold_graph_paths: Sequence[Sequence[Sequence[str]]] | None = None,
    latencies_ms: Iterable[float] = (),
) -> RetrievalMetrics:
    if len(rankings) != len(gold_ids):
        raise ValueError("rankings and gold_ids must have equal length.")
    count = len(rankings)
    if count == 0:
        return RetrievalMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    graph_paths = graph_paths or [[] for _ in range(count)]
    gold_graph_paths = gold_graph_paths or [[] for _ in range(count)]
    if len(graph_paths) != count or len(gold_graph_paths) != count:
        raise ValueError("Graph path inputs must align with rankings.")
    latencies = list(latencies_ms)
    graph_scores = [
        _graph_path_recall(found, expected)
        for found, expected in zip(graph_paths, gold_graph_paths, strict=True)
        if expected
    ]
    return RetrievalMetrics(
        recall_at_1=mean(_recall(items, gold, 1) for items, gold in zip(rankings, gold_ids, strict=True)),
        recall_at_5=mean(_recall(items, gold, 5) for items, gold in zip(rankings, gold_ids, strict=True)),
        recall_at_10=mean(_recall(items, gold, 10) for items, gold in zip(rankings, gold_ids, strict=True)),
        mrr=mean(_reciprocal_rank(items, gold) for items, gold in zip(rankings, gold_ids, strict=True)),
        ndcg_at_5=mean(_ndcg(items, gold, 5) for items, gold in zip(rankings, gold_ids, strict=True)),
        ndcg_at_10=mean(_ndcg(items, gold, 10) for items, gold in zip(rankings, gold_ids, strict=True)),
        graph_path_recall=mean(graph_scores) if graph_scores else 1.0,
        average_latency_ms=mean(latencies) if latencies else 0.0,
    )


def _recall(items: Sequence[str], gold: set[str], k: int) -> float:
    if not gold:
        return 1.0
    return len(set(items[:k]) & gold) / len(gold)


def _reciprocal_rank(items: Sequence[str], gold: set[str]) -> float:
    return next((1.0 / rank for rank, item in enumerate(items, 1) if item in gold), 0.0)


def _ndcg(items: Sequence[str], gold: set[str], k: int) -> float:
    if not gold:
        return 1.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank, item in enumerate(items[:k], 1) if item in gold)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def _graph_path_recall(found: Sequence[Sequence[str]], gold: Sequence[Sequence[str]]) -> float:
    if not gold:
        return 1.0
    found_set = {tuple(path) for path in found}
    return len(found_set & {tuple(path) for path in gold}) / len(gold)
