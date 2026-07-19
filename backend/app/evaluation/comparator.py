from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import (
    CaseResult,
    ComparisonScope,
    EvaluationRun,
    ExecutionEnvironment,
    MetricDelta,
    MetricResult,
    RegressionComparison,
)
from backend.app.evaluation.stable_ids import stable_id


PERFORMANCE_TERMS = ("latency", "token", "cost", "overhead", "throughput", "calls")


def compare_runs(
    *,
    baseline_run: EvaluationRun,
    candidate_run: EvaluationRun,
    baseline_environment: ExecutionEnvironment,
    candidate_environment: ExecutionEnvironment,
    baseline_case_results: list[CaseResult],
    candidate_case_results: list[CaseResult],
    baseline_metrics: list[MetricResult],
    candidate_metrics: list[MetricResult],
    metric_names: dict[str, str] | None = None,
    baseline_binding_id: str,
) -> RegressionComparison:
    metric_names = metric_names or {}
    baseline_case_ids = {item.case_id for item in baseline_case_results}
    candidate_case_ids = {item.case_id for item in candidate_case_results}
    common = sorted(baseline_case_ids & candidate_case_ids)
    reasons: list[str] = []
    if baseline_run.dataset_version_id != candidate_run.dataset_version_id:
        reasons.append("dataset_version_mismatch")
    for field in (
        "case_set_hash", "gold_hash", "fixture_hash", "adapter_major_hash",
        "metric_definition_hash",
    ):
        if getattr(baseline_run.run_fingerprint, field) != getattr(candidate_run.run_fingerprint, field):
            reasons.append(f"{field}_mismatch")
    if baseline_run.mode != candidate_run.mode:
        reasons.append("evaluation_mode_mismatch")
    environment_compatible = baseline_environment.environment_hash == candidate_environment.environment_hash
    if not environment_compatible:
        reasons.append("execution_environment_mismatch")
    base_metrics = {_metric_key(item): item for item in baseline_metrics}
    candidate_metrics_by_key = {_metric_key(item): item for item in candidate_metrics}
    comparable: list[str] = []
    incompatible: list[str] = []
    deltas: list[MetricDelta] = []
    subgroup_deltas: list[MetricDelta] = []
    for key in sorted(set(base_metrics) & set(candidate_metrics_by_key)):
        baseline = base_metrics[key]
        candidate = candidate_metrics_by_key[key]
        name = metric_names.get(baseline.metric_definition_id, baseline.metric_definition_id)
        if any(term in name for term in PERFORMANCE_TERMS) and not environment_compatible:
            incompatible.append(baseline.metric_definition_id)
            continue
        comparable.append(baseline.metric_definition_id)
        absolute = None
        relative = None
        if baseline.value is not None and candidate.value is not None:
            absolute = candidate.value - baseline.value
            if baseline.value == 0:
                relative = 0.0 if candidate.value == 0 else None
            else:
                relative = absolute / abs(baseline.value)
        delta = MetricDelta(
            metric_definition_id=baseline.metric_definition_id,
            subgroup=baseline.subgroup,
            baseline_value=baseline.value,
            candidate_value=candidate.value,
            absolute_delta=absolute,
            relative_delta=relative,
            numerator=candidate.numerator,
            denominator=candidate.denominator,
            sample_count=min(baseline.sample_count, candidate.sample_count),
            complete=baseline.complete and candidate.complete,
        )
        (subgroup_deltas if baseline.subgroup else deltas).append(delta)
    if not common or not comparable or any(reason in reasons for reason in {
        "gold_hash_mismatch", "fixture_hash_mismatch", "adapter_major_hash_mismatch",
        "metric_definition_hash_mismatch",
    }):
        compatibility = "incompatible"
    elif reasons or baseline_case_ids != candidate_case_ids or incompatible:
        compatibility = "partially_compatible"
    else:
        compatibility = "compatible"
    scope = ComparisonScope(
        common_case_ids=common,
        excluded_baseline_case_ids=sorted(baseline_case_ids - set(common)),
        excluded_candidate_case_ids=sorted(candidate_case_ids - set(common)),
        comparable_metric_definition_ids=sorted(set(comparable)),
        incompatible_metric_definition_ids=sorted(set(incompatible)),
        compatibility=compatibility,
        incompatibility_reasons=sorted(set(reasons)),
    )
    payload = [baseline_run.run_id, candidate_run.run_id, scope.model_dump(mode="json")]
    return RegressionComparison(
        comparison_id=stable_id("comparison", payload),
        baseline_binding_id=baseline_binding_id,
        baseline_run_id=baseline_run.run_id,
        candidate_run_id=candidate_run.run_id,
        baseline_subject_id=baseline_run.subject_id,
        candidate_subject_id=candidate_run.subject_id,
        scope=scope,
        metric_deltas=deltas,
        subgroup_deltas=subgroup_deltas,
        status="invalid" if compatibility == "incompatible" else "ready",
        created_at=datetime.now(UTC),
    )


def _metric_key(result: MetricResult) -> tuple[str, tuple[tuple[str, str], ...]]:
    return result.metric_definition_id, tuple(sorted(result.subgroup.items()))
