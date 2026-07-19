from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.app.evaluation.baseline_service import BaselineService
from backend.app.evaluation.comparator import compare_runs
from backend.app.evaluation.mock_runner import build_synthetic_suite
from backend.app.evaluation.regression_gate import RegressionGateEngine
from backend.app.evaluation.schemas import (
    EvaluationProviderBudget,
    GateRule,
    LiveTrialSpec,
    RegressionGateConfig,
)
from backend.app.evaluation.stable_ids import stable_hash
from backend.app.evaluation.store_protocol import EvaluationStoreError
from backend.app.evaluation.subjects import build_evaluation_subject


def _completed_pair():
    suite = build_synthetic_suite()
    baseline = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    baseline = asyncio.run(suite.service.process_run(baseline.run_id))
    subject = build_evaluation_subject(
        subject_type="code_commit",
        code_commit_sha="a" * 40,
        code_tag=None,
        worktree_patch_hash=None,
        config_hash=stable_hash("candidate-config"),
        dependency_lock_hash=stable_hash("synthetic-lock-v1"),
    )
    suite.store.save_subject(subject)
    candidate_request = suite.request.model_copy(update={"subject_id": subject.subject_id})
    candidate = suite.service.prepare_run(candidate_request, caller_scope_hash="test")
    candidate = asyncio.run(suite.service.process_run(candidate.run_id))
    return suite, baseline, candidate


def _gate_config(metric_id: str, *, threshold: float = 1.0, severity: str = "block"):
    rule = GateRule(
        rule_id="task-success",
        metric_definition_id=metric_id,
        scope="overall",
        comparison="min_value",
        threshold=threshold,
        min_sample_count=1,
        incomplete_policy="block",
        severity=severity,
    )
    payload = rule.model_dump(mode="json")
    return RegressionGateConfig(
        gate_config_version=f"gate-{severity}-{threshold}",
        profile_type="ci",
        hard_rules=[rule],
        critical_subgroups=[{"tag": "ci"}],
        config_hash=stable_hash(payload),
        created_at=datetime.now(UTC),
    )


def test_evaluation_run_is_immutable_after_completion():
    suite, baseline, _candidate = _completed_pair()
    with pytest.raises(EvaluationStoreError, match="evaluation_run_immutable"):
        suite.store.update_run(baseline.model_copy(update={"status": "failed"}))


def test_baseline_binding_is_separate_from_run():
    suite, baseline, _candidate = _completed_pair()
    metric_id = next(
        key for key, item in suite.store.metric_definitions.items()
        if item.component == "agent" and item.name == "task_success"
    )
    config = _gate_config(metric_id)
    suite.store.save_gate_config(config)
    binding = BaselineService(suite.store).promote(
        dataset_version_id=baseline.dataset_version_id,
        component="agent",
        evaluation_mode=baseline.mode,
        gate_config=config,
        baseline_run_id=baseline.run_id,
        promoted_by_scope="local-admin",
        promotion_reason_code="verified-ci-baseline",
    )
    assert binding.status == "active"
    assert suite.store.get_run(baseline.run_id) == baseline


def test_partial_run_cannot_be_promoted_to_baseline():
    suite = build_synthetic_suite()
    run = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    for status in ("preparing", "running", "aggregating"):
        run = run.model_copy(update={"status": status})
        suite.store.update_run(run)
    partial = run.model_copy(update={"status": "partial", "complete": False})
    suite.store.update_run(partial)
    config = RegressionGateConfig(
        gate_config_version="gate-empty", profile_type="ci",
        config_hash=stable_hash("empty"), created_at=datetime.now(UTC),
    )
    with pytest.raises(EvaluationStoreError, match="baseline_run_incomplete"):
        BaselineService(suite.store).promote(
            dataset_version_id=partial.dataset_version_id,
            component="agent",
            evaluation_mode=partial.mode,
            gate_config=config,
            baseline_run_id=partial.run_id,
            promoted_by_scope="admin",
            promotion_reason_code="invalid",
        )


def test_run_fingerprint_compatibility_and_gate():
    suite, baseline, candidate = _completed_pair()
    metric_id = next(
        key for key, item in suite.store.metric_definitions.items()
        if item.component == "agent" and item.name == "task_success"
    )
    config = _gate_config(metric_id)
    suite.store.save_gate_config(config)
    binding = BaselineService(suite.store).promote(
        dataset_version_id=baseline.dataset_version_id,
        component="agent",
        evaluation_mode=baseline.mode,
        gate_config=config,
        baseline_run_id=baseline.run_id,
        promoted_by_scope="admin",
        promotion_reason_code="ci",
    )
    comparison = compare_runs(
        baseline_run=baseline,
        candidate_run=candidate,
        baseline_environment=suite.store.get_environment(baseline.environment_id),
        candidate_environment=suite.store.get_environment(candidate.environment_id),
        baseline_case_results=suite.store.list_case_results(baseline.run_id),
        candidate_case_results=suite.store.list_case_results(candidate.run_id),
        baseline_metrics=suite.store.list_metric_results(baseline.run_id),
        candidate_metrics=suite.store.list_metric_results(candidate.run_id),
        baseline_binding_id=binding.baseline_binding_id,
    )
    assert comparison.scope.compatibility == "compatible"
    gate = RegressionGateEngine().evaluate(comparison, config)
    assert gate.verdict == "passed"


def test_warning_rule_does_not_block_release():
    suite, baseline, candidate = _completed_pair()
    metric_id = next(iter(suite.store.metric_definitions))
    config = _gate_config(metric_id, threshold=2.0, severity="warning")
    comparison = compare_runs(
        baseline_run=baseline, candidate_run=candidate,
        baseline_environment=suite.store.get_environment(baseline.environment_id),
        candidate_environment=suite.store.get_environment(candidate.environment_id),
        baseline_case_results=suite.store.list_case_results(baseline.run_id),
        candidate_case_results=suite.store.list_case_results(candidate.run_id),
        baseline_metrics=suite.store.list_metric_results(baseline.run_id),
        candidate_metrics=suite.store.list_metric_results(candidate.run_id),
        baseline_binding_id="binding",
    )
    gate = RegressionGateEngine().evaluate(comparison, config)
    assert gate.verdict == "passed"
    assert gate.hard_invariants[0].verdict in {"warning", "blocked"}


def test_performance_comparison_requires_same_environment():
    suite, baseline, candidate = _completed_pair()
    environment = suite.store.get_environment(candidate.environment_id)
    changed = environment.model_copy(
        update={"environment_id": "different-hardware", "environment_hash": stable_hash("different")}
    )
    suite.store.save_environment(changed)
    candidate = candidate.model_copy(
        update={
            "environment_id": changed.environment_id,
            "run_fingerprint": candidate.run_fingerprint.model_copy(
                update={"environment_hash": changed.environment_hash}
            ),
        }
    )
    metric_names = {
        metric_id: definition.name
        for metric_id, definition in suite.store.metric_definitions.items()
    }
    comparison = compare_runs(
        baseline_run=baseline, candidate_run=candidate,
        baseline_environment=suite.store.get_environment(baseline.environment_id),
        candidate_environment=changed,
        baseline_case_results=suite.store.list_case_results(baseline.run_id),
        candidate_case_results=suite.store.list_case_results(candidate.run_id),
        baseline_metrics=suite.store.list_metric_results(baseline.run_id),
        candidate_metrics=suite.store.list_metric_results(candidate.run_id),
        metric_names=metric_names,
        baseline_binding_id="binding",
    )
    assert comparison.scope.compatibility == "partially_compatible"
    latency_ids = {
        metric_id for metric_id, name in metric_names.items() if "latency" in name
    }
    assert latency_ids & set(comparison.scope.incompatible_metric_definition_ids)


def test_live_trials_have_independent_runs_and_single_trial_cannot_be_baseline():
    suite = build_synthetic_suite()
    live = suite.request.model_copy(
        update={
            "mode": "live_experiment",
            "external_model_consent": True,
            "provider_concurrency": 1,
            "provider_budget": EvaluationProviderBudget(max_requests=10, max_tokens=1000),
            "live_trial": LiveTrialSpec(
                trial_group_id="live-group", repeat_count=2, temperature=0, seed=7,
                seed_supported=True,
            ),
        }
    )
    first = suite.service.prepare_run(live, caller_scope_hash="test", repeat_index=0)
    first = asyncio.run(suite.service.process_run(first.run_id))
    config = RegressionGateConfig(
        gate_config_version="release-live", profile_type="release",
        minimum_live_repeat_count=2, config_hash=stable_hash("release-live"),
        created_at=datetime.now(UTC),
    )
    with pytest.raises(EvaluationStoreError, match="live_repeat_insufficient"):
        BaselineService(suite.store).promote(
            dataset_version_id=first.dataset_version_id, component="agent",
            evaluation_mode="live_experiment", gate_config=config,
            baseline_run_id=first.run_id, promoted_by_scope="admin",
            promotion_reason_code="too-few-trials",
        )
    second = suite.service.prepare_run(live, caller_scope_hash="test", repeat_index=1)
    second = asyncio.run(suite.service.process_run(second.run_id))
    assert first.run_id != second.run_id
    binding = BaselineService(suite.store).promote(
        dataset_version_id=first.dataset_version_id, component="agent",
        evaluation_mode="live_experiment", gate_config=config,
        baseline_run_id=first.run_id, promoted_by_scope="admin",
        promotion_reason_code="repeat-complete",
    )
    assert binding.status == "active"
