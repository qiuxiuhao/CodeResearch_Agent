from __future__ import annotations

from datetime import UTC, datetime

from backend.app.alignment.schemas import (
    AlignmentCandidate,
    CandidateSourceContribution,
    PaperModuleProfile,
)
from backend.app.alignment.stable_ids import candidate_id


def merge_candidate_contributions(
    *,
    profile: PaperModuleProfile,
    contributions_by_entity: dict[str, list[CandidateSourceContribution]],
    code_evidence_by_entity: dict[str, list[str]] | None = None,
    chunks_by_entity: dict[str, list[str]] | None = None,
    limit: int = 20,
) -> list[AlignmentCandidate]:
    code_evidence_by_entity = code_evidence_by_entity or {}
    chunks_by_entity = chunks_by_entity or {}
    candidates: list[AlignmentCandidate] = []
    for entity_id, contributions in contributions_by_entity.items():
        ordered = sorted(
            contributions,
            key=lambda item: (
                item.source_rank if item.source_rank is not None else 1_000_000,
                -(item.normalized_contribution or 0.0),
                item.source,
            ),
        )
        candidates.append(
            AlignmentCandidate(
                candidate_id=candidate_id(
                    profile_id_value=profile.profile_id,
                    index_version_id=profile.index_version_id,
                    code_entity_id=entity_id,
                ),
                alignment_run_id=profile.alignment_run_id,
                profile_id=profile.profile_id,
                code_entity_id=entity_id,
                source_contributions=ordered,
                best_source_rank=min(
                    (item.source_rank for item in ordered if item.source_rank is not None),
                    default=None,
                ),
                code_evidence_ids=sorted(set(code_evidence_by_entity.get(entity_id, []))),
                retrieval_chunk_ids=sorted(set(chunks_by_entity.get(entity_id, []))),
                generated_at=datetime.now(UTC),
            )
        )
    candidates.sort(key=_candidate_rank)
    return candidates[:limit]


def _candidate_rank(item: AlignmentCandidate) -> tuple[float, int, str]:
    best = max((entry.normalized_contribution or 0.0 for entry in item.source_contributions), default=0.0)
    rank = item.best_source_rank if item.best_source_rank is not None else 1_000_000
    return (-best, rank, item.code_entity_id)
