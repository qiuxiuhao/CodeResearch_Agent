from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import EvaluationBaselineBinding, RegressionGateConfig
from backend.app.evaluation.stable_ids import stable_hash, stable_id
from backend.app.evaluation.store_protocol import EvaluationStoreError, EvaluationStoreProtocol


class BaselineService:
    def __init__(self, store: EvaluationStoreProtocol) -> None:
        self.store = store

    def promote(
        self,
        *,
        dataset_version_id: str,
        component: str,
        evaluation_mode: str,
        gate_config: RegressionGateConfig,
        baseline_run_id: str,
        promoted_by_scope: str,
        promotion_reason_code: str,
    ) -> EvaluationBaselineBinding:
        run = self.store.get_run(baseline_run_id)
        if run.status != "completed" or not run.complete:
            raise EvaluationStoreError("baseline_run_incomplete", baseline_run_id)
        if evaluation_mode == "live_experiment":
            required = gate_config.minimum_live_repeat_count or 2
            trials = (
                self.store.list_trial_runs(run.trial_group_id)  # type: ignore[attr-defined]
                if run.trial_group_id and hasattr(self.store, "list_trial_runs") else [run]
            )
            completed_indices = {
                item.repeat_index for item in trials
                if item.status == "completed" and item.complete and item.repeat_index is not None
            }
            if len(completed_indices) < required:
                raise EvaluationStoreError("live_repeat_insufficient", baseline_run_id)
        payload = [dataset_version_id, component, evaluation_mode, gate_config.gate_config_version, baseline_run_id]
        now = datetime.now(UTC)
        source_values = {
            case.source
            for case in self.store.list_cases(dataset_version_id)
            if case.component == component
        }
        if not source_values:
            raise EvaluationStoreError("baseline_component_cases_missing", component)
        source_profile = next(iter(source_values)) if len(source_values) == 1 else "mixed"
        binding = EvaluationBaselineBinding(
            baseline_binding_id=stable_id("baseline", payload),
            dataset_version_id=dataset_version_id,
            component=component,
            evaluation_mode=evaluation_mode,
            dataset_source_profile=source_profile,
            gate_config_version=gate_config.gate_config_version,
            baseline_run_id=baseline_run_id,
            subject_id=run.subject_id,
            status="active",
            promoted_by_scope_hash=stable_hash(promoted_by_scope),
            promotion_reason_code=promotion_reason_code,
            created_at=now,
            promoted_at=now,
        )
        return self.store.promote_baseline(binding)
