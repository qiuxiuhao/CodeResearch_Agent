from __future__ import annotations

from backend.app.agents.research.schemas import (
    EvidenceAssessment,
    EvidenceCriterionResult,
    ResearchRoute,
    ToolObservation,
)
from backend.app.retrieval.schemas import QueryType


class EvidenceSufficiencyChecker:
    def assess(
        self,
        *,
        query_type: QueryType,
        route: ResearchRoute,
        observations: list[ToolObservation],
        has_remaining_steps: bool,
        direct_escalated_to_planned: bool,
        can_replan: bool,
    ) -> EvidenceAssessment:
        successful = [item for item in observations if item.status == "success"]
        entity_ids = _unique(item for obs in successful for item in obs.entity_ids)
        evidence_ids = _unique(item for obs in successful for item in obs.evidence_ids)
        edge_ids = _unique(item for obs in successful for item in obs.edge_ids)
        criteria: list[EvidenceCriterionResult] = []

        code_ok = bool(entity_ids and evidence_ids)
        criteria.append(EvidenceCriterionResult(
            criterion="code_evidence", satisfied=code_ok, evidence_ids=evidence_ids,
            reason=None if code_ok else "No entity with path/page evidence was returned.",
        ))
        graph_required = query_type in {
            "call_chain", "architecture", "training_process", "inference_process", "paper_alignment"
        }
        if graph_required:
            graph_ok = bool(edge_ids)
            criteria.append(EvidenceCriterionResult(
                criterion="graph_evidence", satisfied=graph_ok, evidence_ids=edge_ids,
                reason=None if graph_ok else "No resolved graph edge was returned.",
            ))
        if query_type == "paper_alignment":
            paper_ok = any(obs.tool_name in {"search_paper", "get_alignment"} and obs.status == "success" for obs in successful)
            criteria.append(EvidenceCriterionResult(
                criterion="paper_alignment_evidence", satisfied=paper_ok,
                evidence_ids=evidence_ids + edge_ids,
                reason=None if paper_ok else "No paper/alignment result was returned.",
            ))
        sufficient = bool(criteria) and all(item.satisfied for item in criteria)
        missing = [item.criterion for item in criteria if not item.satisfied]
        if sufficient:
            next_action = "build_context"
        elif has_remaining_steps:
            next_action = "resolve_next"
        elif route == "direct" and not direct_escalated_to_planned:
            next_action = "escalate_to_plan"
        elif route == "planned" and can_replan:
            next_action = "replan"
        else:
            next_action = "partial"
        confidence = 1.0 if sufficient else (sum(item.satisfied for item in criteria) / len(criteria) if criteria else 0.0)
        return EvidenceAssessment(
            query_type=query_type,
            sufficient=sufficient,
            criteria=criteria,
            covered_entity_ids=entity_ids,
            covered_evidence_ids=evidence_ids,
            missing_evidence=missing,
            confidence=confidence,
            next_action=next_action,
            reason_codes=missing,
        )


def _unique(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
