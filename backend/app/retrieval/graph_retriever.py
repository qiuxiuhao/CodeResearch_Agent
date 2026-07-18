from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.retrieval.entity_chunk_selector import EntityChunkSelector
from backend.app.retrieval.schemas import FusedRetrievalCandidate, RawRetrievalHit, RetrievalConfig, RetrievalQuery


@dataclass(frozen=True, slots=True)
class GraphRetrievalResult:
    hits: list[RawRetrievalHit]
    relationship_notes: list[str]


class GraphRetriever:
    def __init__(self, read_store: RetrievalReadStore) -> None:
        self.read_store = read_store

    def expand(
        self,
        *,
        query: RetrievalQuery,
        config: RetrievalConfig,
        graph_seed_candidates: Sequence[FusedRetrievalCandidate],
    ) -> GraphRetrievalResult:
        seeds = list(graph_seed_candidates[: config.graph_seed_k])
        if not seeds or config.graph_max_hops == 0 or not config.graph_edge_weights:
            return GraphRetrievalResult([], [])
        current_hit_ranks = {
            hit.chunk_id: rank
            for rank, candidate in enumerate(seeds, 1)
            for hit in candidate.hits
        }
        seed_scores = [candidate.preliminary_rrf or 0.0 for candidate in seeds]
        maximum = max(seed_scores) or 1.0
        frontier = [
            (candidate.entity_id, (candidate.preliminary_rrf or 0.0) / maximum, [], 0)
            for candidate in seeds
        ]
        best: dict[str, tuple[float, list[str]]] = {}
        notes: list[str] = []
        visited: dict[str, float] = {entity_id: score for entity_id, score, _, _ in frontier}
        while frontier:
            entity_id, score, path, hop = frontier.pop(0)
            if hop >= config.graph_max_hops:
                continue
            edges = self.read_store.graph_neighbors(
                repo_id=query.filters.repo_id,
                index_version_id=query.filters.index_version_id,
                entity_ids=[entity_id],
                edge_types=list(config.graph_edge_weights),
            )
            for edge in edges:
                if edge.target_id is None:
                    if edge.source_id == entity_id:
                        notes.append(f"{entity_id} --{edge.edge_type}--> unresolved:{edge.unresolved_symbol}")
                    continue
                neighbor = edge.target_id if edge.source_id == entity_id else edge.source_id
                next_score = (
                    score * config.graph_edge_weights.get(edge.edge_type, 1.0)
                    * edge.confidence * (0.65 ** (hop + 1))
                )
                next_path = [*path, edge.id]
                if next_score <= visited.get(neighbor, -1.0):
                    continue
                visited[neighbor] = next_score
                best[neighbor] = (next_score, next_path)
                frontier.append((neighbor, next_score, next_path, hop + 1))
                if len(best) >= config.graph_max_candidates:
                    frontier.clear()
                    break
        if not best:
            return GraphRetrievalResult([], sorted(set(notes)))
        chunks = self.read_store.chunks_for_entities(
            repo_id=query.filters.repo_id,
            index_version_id=query.filters.index_version_id,
            entity_ids=sorted(best),
        )
        selector = EntityChunkSelector(current_hit_ranks=current_hit_ranks)
        selected: list[tuple[float, str, str, list[str], str]] = []
        for entity_id, (score, path) in best.items():
            chunk = selector.select(
                entity_id=entity_id,
                query_text=query.text,
                query_profile=config.profile,
                graph_path_edge_ids=path,
                available_chunks=chunks.get(entity_id, []),
            )
            if chunk is None:
                notes.append(f"entity:{entity_id} has no chunk; graph_path={','.join(path)}")
                continue
            selected.append((score, chunk.id, entity_id, path, selector.last_rule or "unknown"))
        selected.sort(key=lambda item: (-item[0], item[2], item[1]))
        hits = [
            RawRetrievalHit(
                source="graph", chunk_id=chunk_id, entity_id=entity_id,
                source_score=score, source_rank=rank,
                metadata={"graph_path_edge_ids": path, "entity_chunk_rule": rule},
            )
            for rank, (score, chunk_id, entity_id, path, rule) in enumerate(selected, 1)
        ]
        return GraphRetrievalResult(hits, sorted(set(notes)))
