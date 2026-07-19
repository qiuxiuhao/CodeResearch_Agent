from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean

from backend.app.evaluation.schemas import (
    AgentGold,
    AgentOutcome,
    AlignmentGold,
    AlignmentOutcome,
    AnswerGold,
    AnswerOutcome,
    CaseResult,
    EvaluationCase,
    IndexGold,
    IndexOutcome,
    MetricDefinition,
    MetricResult,
    ObservabilityOutcome,
    RetrievalGold,
    RetrievalOutcome,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id


def default_metric_definitions() -> list[MetricDefinition]:
    specs = [
        ("index", "case_pass_rate", "higher_is_better", "ratio"),
        ("index", "entity_recall", "higher_is_better", "mean"),
        ("index", "edge_recall", "higher_is_better", "mean"),
        ("index", "evidence_recall", "higher_is_better", "mean"),
        ("index", "chunk_recall", "higher_is_better", "mean"),
        ("retrieval", "recall_at_1", "higher_is_better", "mean"),
        ("retrieval", "recall_at_5", "higher_is_better", "mean"),
        ("retrieval", "recall_at_10", "higher_is_better", "mean"),
        ("retrieval", "recall_at_20", "higher_is_better", "mean"),
        ("retrieval", "mrr", "higher_is_better", "mean"),
        ("retrieval", "ndcg_at_10", "higher_is_better", "mean"),
        ("retrieval", "empty_rate", "lower_is_better", "ratio"),
        ("retrieval", "graph_path_recall", "higher_is_better", "mean"),
        ("retrieval", "fallback_rate", "lower_is_better", "ratio"),
        ("retrieval", "latency_ms", "lower_is_better", "mean"),
        ("agent", "task_success", "higher_is_better", "ratio"),
        ("agent", "route_accuracy", "higher_is_better", "ratio"),
        ("agent", "tool_selection_accuracy", "higher_is_better", "ratio"),
        ("agent", "evidence_sufficiency", "higher_is_better", "ratio"),
        ("agent", "budget_compliance", "higher_is_better", "ratio"),
        ("agent", "invalid_tool_call", "zero_required", "count"),
        ("alignment", "candidate_recall_at_20", "higher_is_better", "mean"),
        ("alignment", "pair_f1", "higher_is_better", "mean"),
        ("alignment", "exact_set", "higher_is_better", "ratio"),
        ("alignment", "selective_accuracy", "higher_is_better", "ratio"),
        ("alignment", "coverage", "higher_is_better", "ratio"),
        ("alignment", "abstention_accuracy", "higher_is_better", "ratio"),
        ("alignment", "no_implementation_accuracy", "higher_is_better", "ratio"),
        ("alignment", "evidence_recall", "higher_is_better", "mean"),
        ("alignment", "brier", "lower_is_better", "calibration"),
        ("alignment", "ece", "lower_is_better", "calibration"),
        ("answer", "case_pass_rate", "higher_is_better", "ratio"),
        ("answer", "claim_coverage", "higher_is_better", "mean"),
        ("answer", "supported_claim_rate", "higher_is_better", "ratio"),
        ("answer", "citation_validity", "higher_is_better", "ratio"),
        ("answer", "answer_completeness", "higher_is_better", "mean"),
        ("observability", "trace_completeness", "higher_is_better", "ratio"),
        ("observability", "integrity_flag_rate", "lower_is_better", "ratio"),
        ("observability", "missing_span_rate", "lower_is_better", "mean"),
        ("observability", "link_validity", "higher_is_better", "ratio"),
        ("observability", "redaction_validity", "higher_is_better", "ratio"),
        ("observability", "drop_rate", "lower_is_better", "mean"),
        ("observability", "secret_leak", "zero_required", "count"),
        ("observability", "recorder_overhead_ms", "lower_is_better", "percentile"),
    ]
    output: list[MetricDefinition] = []
    for component, name, direction, aggregation in specs:
        payload = {"component": component, "name": name, "version": "1"}
        output.append(
            MetricDefinition(
                metric_definition_id=stable_id("metric", payload),
                name=name,
                version="1",
                component=component,
                direction=direction,
                aggregation=aggregation,
                denominator_policy="evaluable_complete_cases",
                empty_input_policy="null",
                requires_complete_input=True,
                subgroup_keys=["split", "source", "repo", "tag", "type"],
                config_hash=stable_hash(payload),
            )
        )
    return output


class MetricEngine:
    def __init__(self, definitions: list[MetricDefinition] | None = None) -> None:
        definitions = definitions or default_metric_definitions()
        self.definitions = {(item.component, item.name): item for item in definitions}

    def compute(
        self,
        *,
        evaluation_run_id: str,
        cases: list[EvaluationCase],
        results: list[CaseResult],
    ) -> list[MetricResult]:
        by_case = {item.case_id: item for item in cases}
        groups: dict[tuple[str, tuple[tuple[str, str], ...]], list[CaseResult]] = defaultdict(list)
        for result in results:
            case = by_case.get(result.case_id)
            if case is None:
                continue
            groups[(result.component, tuple())].append(result)
            groups[(result.component, (("split", case.split),))].append(result)
            groups[(result.component, (("source", case.source),))].append(result)
            groups[(result.component, (("repo", case.repo_id),))].append(result)
            for tag in case.tags:
                groups[(result.component, (("tag", tag),))].append(result)
        output: list[MetricResult] = []
        computed_at = max(
            (item.finished_at for item in results if item.finished_at is not None),
            default=datetime.now(UTC),
        )
        for (component, subgroup_items), rows in groups.items():
            subgroup = dict(subgroup_items)
            component_cases = {item.case_id: by_case[item.case_id] for item in rows}
            for name, value, numerator, denominator, complete, reasons in self._values(
                component, component_cases, rows
            ):
                definition = self.definitions.get((component, name))
                if definition is None:
                    continue
                payload = [evaluation_run_id, definition.metric_definition_id, subgroup]
                output.append(
                    MetricResult(
                        metric_result_id=stable_id("metric_result", payload),
                        evaluation_run_id=evaluation_run_id,
                        metric_definition_id=definition.metric_definition_id,
                        split=subgroup.get("split", "all"),
                        subgroup=subgroup,
                        value=value,
                        numerator=numerator,
                        denominator=denominator,
                        sample_count=int(denominator) if denominator is not None else len(rows),
                        complete=complete,
                        incomplete_reason_codes=reasons,
                        computed_at=computed_at,
                    )
                )
        return output

    def _values(self, component: str, cases: dict[str, EvaluationCase], rows: list[CaseResult]):
        evaluable = [
            item for item in rows
            if item.execution_status == "completed" and item.evaluation_outcome in {"passed", "failed"}
        ]
        complete = len(evaluable) == len(rows) and all(item.complete for item in rows)
        reasons = [] if complete else ["incomplete_or_not_evaluable_case"]
        if component in {"index", "agent", "answer"}:
            passed = sum(item.evaluation_outcome == "passed" for item in evaluable)
            name = "task_success" if component == "agent" else "case_pass_rate"
            yield name, _ratio(passed, len(evaluable)), float(passed), float(len(evaluable)), complete, reasons
            if component == "index":
                categories = {"entity": [], "edge": [], "evidence": [], "chunk": []}
                for item in evaluable:
                    case, outcome = cases[item.case_id], item.outcome
                    if not isinstance(case.gold, IndexGold) or not isinstance(outcome, IndexOutcome):
                        continue
                    categories["entity"].append(_set_recall(outcome.entity_ids, case.gold.required_entity_ids))
                    categories["edge"].append(_set_recall(outcome.edge_ids, case.gold.required_edge_ids))
                    categories["evidence"].append(_set_recall(outcome.evidence_ids, case.gold.required_evidence_ids))
                    categories["chunk"].append(_set_recall(outcome.chunk_ids, case.gold.required_chunk_ids))
                for category, values in categories.items():
                    yield f"{category}_recall", _mean(values), sum(values), float(len(values)), complete, reasons
            if component == "agent":
                invalid = sum("agent_forbidden_tool" in item.quality_failure_codes for item in rows)
                yield "invalid_tool_call", float(invalid), float(invalid), float(len(rows)), complete, reasons
                route_ok = tool_ok = evidence_ok = budget_ok = 0
                for item in evaluable:
                    case, outcome = cases[item.case_id], item.outcome
                    if not isinstance(case.gold, AgentGold) or not isinstance(outcome, AgentOutcome):
                        continue
                    tools = [str(call.get("tool_name", "")) for call in outcome.tool_calls]
                    route_ok += outcome.route == case.gold.expected_route
                    tool_ok += set(case.gold.required_tools) <= set(tools) and not (
                        set(case.gold.forbidden_tools) & set(tools)
                    )
                    evidence_ok += set(case.gold.required_evidence_ids) <= set(outcome.evidence_ids)
                    budget_ok += len(tools) <= case.gold.max_tool_calls
                denominator = len(evaluable)
                yield "route_accuracy", _ratio(route_ok, denominator), float(route_ok), float(denominator), complete, reasons
                yield "tool_selection_accuracy", _ratio(tool_ok, denominator), float(tool_ok), float(denominator), complete, reasons
                yield "evidence_sufficiency", _ratio(evidence_ok, denominator), float(evidence_ok), float(denominator), complete, reasons
                yield "budget_compliance", _ratio(budget_ok, denominator), float(budget_ok), float(denominator), complete, reasons
            if component == "answer":
                coverages: list[float] = []
                supported = total_claims = citations_valid = citations_total = 0
                for item in evaluable:
                    case, outcome = cases[item.case_id], item.outcome
                    if not isinstance(case.gold, AnswerGold) or not isinstance(outcome, AnswerOutcome):
                        continue
                    coverage = _set_recall(outcome.answer_point_ids, case.gold.required_answer_points)
                    coverages.append(coverage)
                    total_claims += len(outcome.claims)
                    supported += sum(bool(claim.get("supported", False)) for claim in outcome.claims)
                    citations_total += len(outcome.citation_ids)
                    allowed = {citation for group in case.gold.allowed_citation_sets for citation in group}
                    citations_valid += sum(citation in allowed for citation in outcome.citation_ids) if allowed else len(outcome.citation_ids)
                yield "claim_coverage", _mean(coverages), sum(coverages), float(len(coverages)), complete, reasons
                yield "answer_completeness", _mean(coverages), sum(coverages), float(len(coverages)), complete, reasons
                yield "supported_claim_rate", _ratio(supported, total_claims), float(supported), float(total_claims), complete, reasons
                yield "citation_validity", _ratio(citations_valid, citations_total), float(citations_valid), float(citations_total), complete, reasons
            return
        if component == "retrieval":
            recalls = {1: [], 5: [], 10: [], 20: []}
            reciprocal: list[float] = []
            ndcgs: list[float] = []
            empty = 0
            fallback = 0
            graph_path_recalls: list[float] = []
            latencies: list[float] = []
            for item in evaluable:
                case, outcome = cases[item.case_id], item.outcome
                if not isinstance(case.gold, RetrievalGold) or not isinstance(outcome, RetrievalOutcome):
                    continue
                ranking = outcome.ranked_entity_ids + outcome.ranked_chunk_ids
                gold = set(case.gold.required_entity_ids + case.gold.required_chunk_ids)
                empty += not ranking
                for k in recalls:
                    recalls[k].append(_recall(ranking, gold, k))
                reciprocal.append(_reciprocal_rank(ranking, gold))
                ndcgs.append(_ndcg(ranking, gold, 10))
                required_paths = {tuple(path) for path in case.gold.required_paths}
                found_paths = {tuple(path) for path in outcome.graph_paths}
                graph_path_recalls.append(
                    len(required_paths & found_paths) / len(required_paths) if required_paths else 1.0
                )
                fallback += bool(outcome.fallback_reason_codes)
                if item.latency_ms is not None:
                    latencies.append(item.latency_ms)
            for k, values in recalls.items():
                yield f"recall_at_{k}", _mean(values), sum(values), float(len(values)), complete, reasons
            yield "mrr", _mean(reciprocal), sum(reciprocal), float(len(reciprocal)), complete, reasons
            yield "ndcg_at_10", _mean(ndcgs), sum(ndcgs), float(len(ndcgs)), complete, reasons
            yield "empty_rate", _ratio(empty, len(evaluable)), float(empty), float(len(evaluable)), complete, reasons
            yield "graph_path_recall", _mean(graph_path_recalls), sum(graph_path_recalls), float(len(graph_path_recalls)), complete, reasons
            yield "fallback_rate", _ratio(fallback, len(evaluable)), float(fallback), float(len(evaluable)), complete, reasons
            yield "latency_ms", _mean(latencies), sum(latencies), float(len(latencies)), complete, reasons
            return
        if component == "alignment":
            recalls: list[float] = []
            f1s: list[float] = []
            exacts: list[float] = []
            probabilities: list[float] = []
            labels: list[int] = []
            accepted_correct = accepted_count = abstention_correct = abstention_count = 0
            no_impl_correct = no_impl_count = 0
            evidence_recalls: list[float] = []
            for item in evaluable:
                case, outcome = cases[item.case_id], item.outcome
                if not isinstance(case.gold, AlignmentGold) or not isinstance(outcome, AlignmentOutcome):
                    continue
                gold_ids = {selection.code_entity_id for selection in case.gold.gold_selections}
                recalls.append(_recall(outcome.candidate_ids, gold_ids, 20))
                gold_pairs = {(x.code_entity_id, x.relation_type) for x in case.gold.gold_selections}
                found_pairs = {(x.code_entity_id, x.relation_type) for x in outcome.selections}
                f1s.append(_f1(found_pairs, gold_pairs))
                exacts.append(float(found_pairs == gold_pairs))
                if outcome.decision_status == "accepted":
                    accepted_count += 1
                    accepted_correct += found_pairs == gold_pairs
                if outcome.decision_status in {"abstained", "needs_review"}:
                    abstention_count += 1
                    abstention_correct += not case.gold.alignable
                if outcome.decision_status == "no_implementation":
                    no_impl_count += 1
                    no_impl_correct += case.gold.no_implementation_expected
                required_evidence = set(
                    case.gold.required_paper_evidence_ids + case.gold.required_code_evidence_ids
                )
                found_evidence = set(outcome.paper_evidence_ids + outcome.code_evidence_ids)
                evidence_recalls.append(
                    len(required_evidence & found_evidence) / len(required_evidence)
                    if required_evidence else 1.0
                )
                for candidate_id, probability in outcome.candidate_probabilities.items():
                    probabilities.append(probability)
                    labels.append(int(candidate_id in gold_ids))
            yield "candidate_recall_at_20", _mean(recalls), sum(recalls), float(len(recalls)), complete, reasons
            yield "pair_f1", _mean(f1s), sum(f1s), float(len(f1s)), complete, reasons
            yield "exact_set", _mean(exacts), sum(exacts), float(len(exacts)), complete, reasons
            yield "selective_accuracy", _ratio(accepted_correct, accepted_count), float(accepted_correct), float(accepted_count), complete, reasons
            yield "coverage", _ratio(accepted_count, len(evaluable)), float(accepted_count), float(len(evaluable)), complete, reasons
            yield "abstention_accuracy", _ratio(abstention_correct, abstention_count), float(abstention_correct), float(abstention_count), complete, reasons
            yield "no_implementation_accuracy", _ratio(no_impl_correct, no_impl_count), float(no_impl_correct), float(no_impl_count), complete, reasons
            yield "evidence_recall", _mean(evidence_recalls), sum(evidence_recalls), float(len(evidence_recalls)), complete, reasons
            brier = _mean([(prob - label) ** 2 for prob, label in zip(probabilities, labels, strict=True)])
            yield "brier", brier, None, float(len(labels)), complete and bool(labels), reasons or (["no_probability_labels"] if not labels else [])
            ece = _ece(probabilities, labels, bins=10)
            yield "ece", ece, None, float(len(labels)), complete and bool(labels), reasons or (["no_probability_labels"] if not labels else [])
            return
        if component == "observability":
            outcomes = [item.outcome for item in evaluable if isinstance(item.outcome, ObservabilityOutcome)]
            complete_count = sum(item.completeness == "complete" for item in outcomes)
            drop_values = [float(item.drop_count) for item in outcomes]
            secret_leaks = sum(
                "observability_forbidden_attribute" in item.quality_failure_codes for item in rows
            )
            yield "trace_completeness", _ratio(complete_count, len(outcomes)), float(complete_count), float(len(outcomes)), complete, reasons
            integrity_count = sum(bool(item.integrity_flags) for item in outcomes)
            missing = [float(item.missing_span_count) for item in outcomes]
            link_valid = sum("observability_link_missing" not in item.quality_failure_codes for item in rows)
            redaction_valid = len(rows) - secret_leaks
            yield "integrity_flag_rate", _ratio(integrity_count, len(outcomes)), float(integrity_count), float(len(outcomes)), complete, reasons
            yield "missing_span_rate", _mean(missing), sum(missing), float(len(missing)), complete, reasons
            yield "link_validity", _ratio(link_valid, len(rows)), float(link_valid), float(len(rows)), complete, reasons
            yield "redaction_validity", _ratio(redaction_valid, len(rows)), float(redaction_valid), float(len(rows)), complete, reasons
            yield "drop_rate", _mean(drop_values), sum(drop_values), float(len(drop_values)), complete, reasons
            yield "secret_leak", float(secret_leaks), float(secret_leaks), float(len(rows)), complete, reasons


def _ratio(numerator: int | float, denominator: int) -> float | None:
    return float(numerator) / denominator if denominator else None


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _recall(ranking: list[str], gold: set[str], k: int) -> float:
    return len(set(ranking[:k]) & gold) / len(gold) if gold else 1.0


def _reciprocal_rank(ranking: list[str], gold: set[str]) -> float:
    return next((1 / index for index, item in enumerate(ranking, 1) if item in gold), 0.0)


def _ndcg(ranking: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 1.0
    score = sum(1 / math.log2(index + 1) for index, item in enumerate(ranking[:k], 1) if item in gold)
    ideal = sum(1 / math.log2(index + 1) for index in range(1, min(len(gold), k) + 1))
    return score / ideal if ideal else 0.0


def _f1(found: set[tuple[str, str]], gold: set[tuple[str, str]]) -> float:
    if not found and not gold:
        return 1.0
    overlap = len(found & gold)
    precision = overlap / len(found) if found else 0
    recall = overlap / len(gold) if gold else 0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _set_recall(found: list[str], gold: list[str]) -> float:
    expected = set(gold)
    return len(set(found) & expected) / len(expected) if expected else 1.0


def _ece(probabilities: list[float], labels: list[int], *, bins: int) -> float | None:
    if not probabilities:
        return None
    total = len(probabilities)
    score = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            (probability, label)
            for probability, label in zip(probabilities, labels, strict=True)
            if (
                lower <= probability <= upper
                if index == bins - 1
                else lower <= probability < upper
            )
        ]
        if not members:
            continue
        confidence = sum(item[0] for item in members) / len(members)
        accuracy = sum(item[1] for item in members) / len(members)
        score += len(members) / total * abs(confidence - accuracy)
    return score
