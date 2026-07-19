from __future__ import annotations

from backend.app.evaluation.adapter import BaseEvaluationAdapter
from backend.app.evaluation.schemas import (
    AgentGold,
    AgentOutcome,
    AlignmentGold,
    AlignmentOutcome,
    AnswerGold,
    AnswerOutcome,
    EvaluationCase,
    EvaluationOutcome,
    IndexGold,
    IndexOutcome,
    ObservabilityGold,
    ObservabilityOutcome,
    RetrievalGold,
    RetrievalOutcome,
)


class IndexEvaluationAdapter(BaseEvaluationAdapter):
    component = "index"

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        gold, actual = case.gold, outcome
        assert isinstance(gold, IndexGold) and isinstance(actual, IndexOutcome)
        failures = _missing("entity", gold.required_entity_ids, actual.entity_ids)
        failures += _missing("edge", gold.required_edge_ids, actual.edge_ids)
        failures += _missing("evidence", gold.required_evidence_ids, actual.evidence_ids)
        failures += _missing("chunk", gold.required_chunk_ids, actual.chunk_ids)
        if not set(actual.unresolved_symbols) <= set(gold.allowed_unresolved_symbols):
            failures.append("index_unexpected_unresolved_symbol")
        return failures


class RetrievalEvaluationAdapter(BaseEvaluationAdapter):
    component = "retrieval"

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        gold, actual = case.gold, outcome
        assert isinstance(gold, RetrievalGold) and isinstance(actual, RetrievalOutcome)
        failures = _missing("entity", gold.required_entity_ids, actual.ranked_entity_ids)
        failures += _missing("chunk", gold.required_chunk_ids, actual.ranked_chunk_ids)
        if gold.required_paths and not {tuple(path) for path in gold.required_paths} <= {
            tuple(path) for path in actual.graph_paths
        }:
            failures.append("retrieval_graph_path_missing")
        return failures


class AgentEvaluationAdapter(BaseEvaluationAdapter):
    component = "agent"

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        gold, actual = case.gold, outcome
        assert isinstance(gold, AgentGold) and isinstance(actual, AgentOutcome)
        failures: list[str] = []
        tools = [str(item.get("tool_name", "")) for item in actual.tool_calls]
        if actual.route != gold.expected_route:
            failures.append("agent_route_mismatch")
        if not set(gold.required_tools) <= set(tools):
            failures.append("agent_required_tool_missing")
        if set(gold.forbidden_tools) & set(tools):
            failures.append("agent_forbidden_tool")
        if len(tools) > gold.max_tool_calls:
            failures.append("agent_tool_budget_exceeded")
        failures += _missing("evidence", gold.required_evidence_ids, actual.evidence_ids)
        failures += _missing("edge", gold.required_edge_ids, actual.edge_ids)
        if actual.terminal_status != gold.expected_terminal_status:
            failures.append("agent_terminal_status_mismatch")
        return failures


class AlignmentEvaluationAdapter(BaseEvaluationAdapter):
    component = "alignment"

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        gold, actual = case.gold, outcome
        assert isinstance(gold, AlignmentGold) and isinstance(actual, AlignmentOutcome)
        expected = {(item.code_entity_id, item.relation_type) for item in gold.gold_selections}
        found = {(item.code_entity_id, item.relation_type) for item in actual.selections}
        alternatives = [
            {(item.code_entity_id, item.relation_type) for item in group}
            for group in gold.acceptable_alternative_sets
        ]
        if found != expected and found not in alternatives:
            return ["alignment_selection_mismatch"]
        return []


class AnswerEvaluationAdapter(BaseEvaluationAdapter):
    component = "answer"

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        gold, actual = case.gold, outcome
        assert isinstance(gold, AnswerGold) and isinstance(actual, AnswerOutcome)
        failures = _missing("answer_point", gold.required_answer_points, actual.answer_point_ids)
        failures += _missing("evidence", gold.required_evidence_ids, actual.evidence_ids)
        claims = {str(item.get("text", "")) for item in actual.claims}
        if set(gold.forbidden_claims) & claims:
            failures.append("answer_forbidden_claim")
        if actual.partial != gold.partial_expected:
            failures.append("answer_partial_mismatch")
        return failures


class ObservabilityEvaluationAdapter(BaseEvaluationAdapter):
    component = "observability"

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        gold, actual = case.gold, outcome
        assert isinstance(gold, ObservabilityGold) and isinstance(actual, ObservabilityOutcome)
        failures = _missing("operation", gold.required_operations, actual.operation_names)
        if set(gold.forbidden_attributes) & set(actual.observed_attribute_keys):
            failures.append("observability_forbidden_attribute")
        if actual.completeness != gold.required_integrity_state:
            failures.append("observability_completeness_mismatch")
        if not set(actual.integrity_flags) <= set(gold.allowed_integrity_flags):
            failures.append("observability_unexpected_integrity_flag")
        if actual.drop_count > gold.max_drop_count:
            failures.append("observability_drop_exceeded")
        if actual.missing_span_count > gold.max_missing_span_count:
            failures.append("observability_missing_span_exceeded")
        return failures


def _missing(kind: str, expected: list[str], actual: list[str]) -> list[str]:
    return [f"{kind}_missing"] if not set(expected) <= set(actual) else []
