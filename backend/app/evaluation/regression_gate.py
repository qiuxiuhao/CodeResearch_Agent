from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import (
    GateRule,
    GateRuleResult,
    MetricDelta,
    RegressionComparison,
    RegressionGate,
    RegressionGateConfig,
)
from backend.app.evaluation.stable_ids import stable_id


class RegressionGateEngine:
    def evaluate(
        self, comparison: RegressionComparison, config: RegressionGateConfig
    ) -> RegressionGate:
        if comparison.scope.compatibility == "incompatible":
            return RegressionGate(
                gate_id=stable_id("gate", [comparison.comparison_id, config.gate_config_version]),
                comparison_id=comparison.comparison_id,
                gate_config_version=config.gate_config_version,
                verdict="indeterminate",
                reason_codes=["comparison_incompatible"],
                evaluated_at=datetime.now(UTC),
            )
        deltas = comparison.metric_deltas + comparison.subgroup_deltas
        hard = [self._evaluate_rule(rule, deltas, hard=True) for rule in config.hard_rules]
        quality = [self._evaluate_rule(rule, deltas) for rule in config.quality_rules]
        performance = [self._evaluate_rule(rule, deltas) for rule in config.performance_rules]
        all_results = hard + quality + performance
        if any(item.verdict == "blocked" for item in all_results):
            verdict = "blocked"
        elif any(item.verdict == "indeterminate" for item in all_results):
            verdict = "indeterminate"
        else:
            verdict = "passed"
        return RegressionGate(
            gate_id=stable_id("gate", [comparison.comparison_id, config.gate_config_version]),
            comparison_id=comparison.comparison_id,
            gate_config_version=config.gate_config_version,
            hard_invariants=hard,
            quality_rules=quality,
            performance_rules=performance,
            verdict=verdict,
            reason_codes=sorted({reason for item in all_results for reason in item.reason_codes}),
            evaluated_at=datetime.now(UTC),
        )

    def _evaluate_rule(
        self, rule: GateRule, deltas: list[MetricDelta], *, hard: bool = False
    ) -> GateRuleResult:
        matches = [
            item for item in deltas
            if item.metric_definition_id == rule.metric_definition_id
            and all(item.subgroup.get(key) == value for key, value in rule.subgroup_filter.items())
        ]
        if not matches:
            return self._incomplete(rule, "gate_metric_missing", hard)
        row = matches[0]
        if row.sample_count < rule.min_sample_count or not row.complete:
            return self._incomplete(rule, "gate_input_incomplete", hard, row)
        passed = _passes(rule, row)
        verdict = "passed" if passed else ("blocked" if rule.severity == "block" else "warning")
        return GateRuleResult(
            rule_id=rule.rule_id,
            verdict=verdict,
            sample_count=row.sample_count,
            numerator=row.numerator,
            denominator=row.denominator,
            baseline_value=row.baseline_value,
            candidate_value=row.candidate_value,
            absolute_delta=row.absolute_delta,
            relative_delta=row.relative_delta,
            reason_codes=[] if passed else ["gate_rule_threshold_failed"],
        )

    def _incomplete(
        self, rule: GateRule, reason: str, hard: bool, row: MetricDelta | None = None
    ) -> GateRuleResult:
        if hard and rule.incomplete_policy != "ignore":
            verdict = "blocked"
        elif rule.incomplete_policy == "block":
            verdict = "blocked"
        elif rule.incomplete_policy == "warning":
            verdict = "warning"
        else:
            verdict = "passed"
        return GateRuleResult(
            rule_id=rule.rule_id,
            verdict=verdict,
            sample_count=row.sample_count if row else 0,
            numerator=row.numerator if row else None,
            denominator=row.denominator if row else None,
            baseline_value=row.baseline_value if row else None,
            candidate_value=row.candidate_value if row else None,
            absolute_delta=row.absolute_delta if row else None,
            relative_delta=row.relative_delta if row else None,
            reason_codes=[reason],
        )


def _passes(rule: GateRule, row: MetricDelta) -> bool:
    if rule.comparison == "equal_zero":
        return row.candidate_value == 0
    if row.candidate_value is None:
        return False
    if rule.comparison == "min_value":
        return row.candidate_value >= rule.threshold
    if rule.comparison == "max_value":
        return row.candidate_value <= rule.threshold
    if rule.comparison == "max_absolute_drop":
        return row.absolute_delta is not None and row.absolute_delta >= -abs(rule.threshold)
    if rule.comparison == "max_relative_drop":
        if row.baseline_value == 0:
            return row.candidate_value == 0
        return row.relative_delta is not None and row.relative_delta >= -abs(rule.threshold)
    return False
