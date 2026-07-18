from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.alignment.candidate_merger import merge_candidate_contributions
from backend.app.alignment.paper_module_extractor import normalize_concept
from backend.app.alignment.schemas import (
    AlignmentCandidate,
    AlignmentSource,
    CandidateSourceContribution,
    PaperModuleProfile,
)
from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity


CANDIDATE_GENERATOR_VERSION = "candidate-generator-v1"
ROLE_TERMS = {
    "encoder",
    "decoder",
    "attention",
    "loss",
    "backbone",
    "head",
    "training",
    "inference",
    "configuration",
}


@dataclass(frozen=True)
class ExternalRecallHit:
    source: AlignmentSource
    code_entity_id: str
    rank: int
    score: float | None = None
    evidence_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    details: dict = field(default_factory=dict)


def generate_alignment_candidates(
    *,
    profile: PaperModuleProfile,
    code_entities: list[CodeEntity],
    edges: list[KnowledgeEdge] | None = None,
    external_hits: list[ExternalRecallHit] | None = None,
    legacy_entity_ids: list[str] | None = None,
    limit: int = 20,
    graph_max_hops: int = 2,
) -> list[AlignmentCandidate]:
    entities = {item.id: item for item in code_entities if item.repo_id == profile.repo_id}
    contributions: dict[str, list[CandidateSourceContribution]] = {}
    evidence: dict[str, list[str]] = {item.id: list(item.evidence_refs) for item in entities.values()}
    chunks: dict[str, list[str]] = {}

    names = _profile_names(profile)
    for entity in entities.values():
        entity_names = _entity_names(entity)
        if names & entity_names:
            _add(contributions, entity.id, "deterministic_rule", 1, 1.0, profile.evidence_ids, {"match": "exact"})
            continue
        overlap = _token_overlap(names, entity_names)
        if overlap > 0:
            _add(contributions, entity.id, "deterministic_rule", None, overlap, profile.evidence_ids, {"match": "normalized"})
        if profile.role and profile.role in _entity_text(entity):
            _add(contributions, entity.id, "deterministic_rule", None, 0.65, profile.evidence_ids, {"match": "role"})
        if profile.figure_neighbor_ids and entity.entity_type in {"model_module", "class", "method"}:
            _add(
                contributions,
                entity.id,
                "figure_vlm",
                None,
                0.35,
                profile.figure_neighbor_ids,
                {"match": "figure_topology_seed"},
            )

    for hit in external_hits or []:
        if hit.code_entity_id not in entities:
            continue
        normalized = 1.0 / max(1, hit.rank)
        _add(
            contributions,
            hit.code_entity_id,
            hit.source,
            hit.rank,
            normalized,
            list(hit.evidence_ids),
            {"raw_score": hit.score, **hit.details},
        )
        chunks.setdefault(hit.code_entity_id, []).extend(hit.chunk_ids)

    for rank, entity_id in enumerate(legacy_entity_ids or [], start=1):
        if entity_id in entities:
            _add(contributions, entity_id, "legacy_alignment", rank, 1.0 / rank, profile.evidence_ids, {})

    seeds = set(contributions)
    for entity_id, depth, edge_ids in _graph_expand(seeds, edges or [], graph_max_hops):
        if entity_id not in entities:
            continue
        _add(
            contributions,
            entity_id,
            "code_graph",
            depth,
            0.65 ** depth,
            edge_ids,
            {"hop": depth, "edge_ids": edge_ids},
        )

    return merge_candidate_contributions(
        profile=profile,
        contributions_by_entity=contributions,
        code_evidence_by_entity=evidence,
        chunks_by_entity=chunks,
        limit=limit,
    )


def _add(
    output: dict[str, list[CandidateSourceContribution]],
    entity_id: str,
    source: AlignmentSource,
    rank: int | None,
    contribution: float,
    evidence_ids: list[str],
    details: dict,
) -> None:
    output.setdefault(entity_id, []).append(
        CandidateSourceContribution(
            source=source,
            source_rank=rank,
            source_score=details.get("raw_score"),
            normalized_contribution=max(0.0, contribution),
            evidence_ids=sorted(set(evidence_ids)),
            details=details,
        )
    )


def _profile_names(profile: PaperModuleProfile) -> set[str]:
    return {value for item in [profile.canonical_name, *profile.aliases, *profile.abbreviations] if (value := normalize_concept(item))}


def _entity_names(entity: CodeEntity) -> set[str]:
    return {
        value
        for item in (entity.name, entity.qualified_name, entity.path)
        if (value := normalize_concept(item))
    }


def _token_overlap(left: set[str], right: set[str]) -> float:
    left_tokens = {token for value in left for token in value.split() if token not in {"module", "model"}}
    right_tokens = {token for value in right for token in value.split() if token not in {"module", "model"}}
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    return len(intersection) / len(left_tokens | right_tokens)


def _entity_text(entity: CodeEntity) -> str:
    return normalize_concept(" ".join([entity.name, entity.qualified_name, entity.path, entity.docstring or ""]))


def _graph_expand(
    seeds: set[str], edges: list[KnowledgeEdge], max_hops: int
) -> list[tuple[str, int, list[str]]]:
    adjacency: dict[str, list[tuple[str, str]]] = {}
    allowed = {"CONTAINS", "DEFINES", "CALLS", "INSTANTIATES", "IMPORTS", "NEXT_MODULE"}
    for edge in edges:
        if edge.edge_type not in allowed or not edge.target_id:
            continue
        adjacency.setdefault(edge.source_id, []).append((edge.target_id, edge.id))
        adjacency.setdefault(edge.target_id, []).append((edge.source_id, edge.id))
    queue = [(seed, 0, []) for seed in sorted(seeds)]
    best = {seed: 0 for seed in seeds}
    result: list[tuple[str, int, list[str]]] = []
    while queue:
        current, depth, path = queue.pop(0)
        if depth >= max_hops:
            continue
        for target, edge_id in sorted(adjacency.get(current, [])):
            next_depth = depth + 1
            if best.get(target, 99) <= next_depth:
                continue
            best[target] = next_depth
            next_path = [*path, edge_id]
            result.append((target, next_depth, next_path))
            queue.append((target, next_depth, next_path))
    return result
