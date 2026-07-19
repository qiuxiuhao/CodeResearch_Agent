from __future__ import annotations

from dataclasses import replace
from threading import RLock

from backend.app.evaluation.schemas import (
    BadCase,
    BadCaseEvent,
    BadCaseOccurrence,
    BadCaseVerification,
    CaseResult,
    EvaluationBaselineBinding,
    EvaluationArtifactRef,
    EvaluationCase,
    EvaluationDataset,
    EvaluationDatasetVersion,
    EvaluationPlan,
    EvaluationRun,
    EvaluationSubject,
    ExecutionEnvironment,
    MetricDefinition,
    MetricResult,
    RegressionComparison,
    RegressionCasePromotion,
    ReplayManifest,
    RegressionGate,
    RegressionGateConfig,
)
from backend.app.evaluation.store_protocol import EvaluationStoreError
from backend.app.evaluation.subjects import (
    EvaluationSubjectError,
    require_formal_baseline_subject,
    validate_subject_hash,
)


TERMINAL_RUN_STATUSES = {"completed", "partial", "failed", "cancelled"}
RUN_TRANSITIONS = {
    "queued": {"preparing", "failed", "cancelled"},
    "preparing": {"running", "failed", "cancelled"},
    "running": {"aggregating", "failed", "cancelled"},
    "aggregating": {"comparing", "completed", "partial", "failed", "cancelled"},
    "comparing": {"completed", "partial", "failed", "cancelled"},
}


class InMemoryEvaluationStore:
    """Deterministic contract store used by v1.9-a through v1.9-e and tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.subjects: dict[str, EvaluationSubject] = {}
        self.artifact_refs: dict[str, EvaluationArtifactRef] = {}
        self.datasets: dict[str, EvaluationDataset] = {}
        self.versions: dict[str, EvaluationDatasetVersion] = {}
        self.cases: dict[str, EvaluationCase] = {}
        self.environments: dict[str, ExecutionEnvironment] = {}
        self.plans: dict[str, EvaluationPlan] = {}
        self.runs: dict[str, EvaluationRun] = {}
        self.case_results: dict[str, CaseResult] = {}
        self.metric_definitions: dict[str, MetricDefinition] = {}
        self.metric_results: dict[str, MetricResult] = {}
        self.comparisons: dict[str, RegressionComparison] = {}
        self.gate_configs: dict[str, RegressionGateConfig] = {}
        self.gates: dict[str, RegressionGate] = {}
        self.baseline_bindings: dict[str, EvaluationBaselineBinding] = {}
        self.bad_cases: dict[str, BadCase] = {}
        self.bad_case_occurrences: dict[str, BadCaseOccurrence] = {}
        self.bad_case_events: dict[str, BadCaseEvent] = {}
        self.bad_case_verifications: dict[str, BadCaseVerification] = {}
        self.promotions: dict[str, RegressionCasePromotion] = {}
        self.replay_manifests: dict[str, ReplayManifest] = {}

    def _immutable_put(self, mapping: dict, key: str, value, error_code: str) -> None:
        with self._lock:
            existing = mapping.get(key)
            if existing is not None and existing != value:
                raise EvaluationStoreError(error_code, key)
            mapping[key] = value

    def save_subject(self, subject: EvaluationSubject) -> None:
        try:
            validate_subject_hash(subject)
        except EvaluationSubjectError as exc:
            raise EvaluationStoreError(str(exc)) from exc
        self._immutable_put(self.subjects, subject.subject_id, subject, "evaluation_subject_immutable")

    def get_subject(self, subject_id: str) -> EvaluationSubject:
        try:
            return self.subjects[subject_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_subject_not_found", subject_id) from exc

    def save_artifact_ref(self, artifact_ref: EvaluationArtifactRef) -> None:
        self._immutable_put(
            self.artifact_refs, artifact_ref.artifact_ref_id, artifact_ref,
            "evaluation_artifact_ref_immutable",
        )

    def get_artifact_ref(self, artifact_ref_id: str) -> EvaluationArtifactRef:
        try:
            return self.artifact_refs[artifact_ref_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_artifact_not_found", artifact_ref_id) from exc

    def save_dataset(self, dataset: EvaluationDataset) -> None:
        with self._lock:
            existing = self.datasets.get(dataset.dataset_id)
            if existing and existing.status != "draft" and existing != dataset:
                raise EvaluationStoreError("evaluation_dataset_immutable", dataset.dataset_id)
            self.datasets[dataset.dataset_id] = dataset

    def save_dataset_version(self, version: EvaluationDatasetVersion) -> None:
        existing = self.versions.get(version.dataset_version_id)
        if existing and existing.status == "frozen" and existing != version:
            raise EvaluationStoreError("evaluation_dataset_version_frozen", version.dataset_version_id)
        self._immutable_put(
            self.versions, version.dataset_version_id, version,
            "evaluation_dataset_version_immutable" if existing else "evaluation_dataset_version_conflict",
        )

    def get_dataset_version(self, version_id: str) -> EvaluationDatasetVersion:
        try:
            return self.versions[version_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_dataset_version_not_found", version_id) from exc

    def save_case(self, case: EvaluationCase) -> None:
        version = self.get_dataset_version(case.dataset_version_id)
        if version.status == "frozen" and case.case_id not in self.cases:
            raise EvaluationStoreError("evaluation_dataset_version_frozen", version.dataset_version_id)
        self._immutable_put(self.cases, case.case_id, case, "evaluation_case_immutable")

    def list_cases(self, version_id: str, case_ids: list[str] | None = None) -> list[EvaluationCase]:
        requested = set(case_ids or [])
        rows = [
            case for case in self.cases.values()
            if case.dataset_version_id == version_id and (not requested or case.case_id in requested)
        ]
        if requested and {case.case_id for case in rows} != requested:
            raise EvaluationStoreError("evaluation_case_not_found")
        return sorted(rows, key=lambda item: item.case_id)

    def save_environment(self, environment: ExecutionEnvironment) -> None:
        self._immutable_put(
            self.environments, environment.environment_id, environment,
            "evaluation_environment_immutable",
        )

    def get_environment(self, environment_id: str) -> ExecutionEnvironment:
        try:
            return self.environments[environment_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_environment_not_found", environment_id) from exc

    def save_plan(self, plan: EvaluationPlan) -> None:
        self._immutable_put(self.plans, plan.plan_id, plan, "evaluation_plan_immutable")

    def get_plan(self, plan_id: str) -> EvaluationPlan:
        try:
            return self.plans[plan_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_plan_not_found", plan_id) from exc

    def save_run(self, run: EvaluationRun, *, caller_scope_hash: str = "") -> None:
        self._immutable_put(self.runs, run.run_id, run, "evaluation_run_conflict")

    def get_run(self, run_id: str) -> EvaluationRun:
        try:
            return self.runs[run_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_run_not_found", run_id) from exc

    def find_reusable_run(self, run_fingerprint_hash: str) -> EvaluationRun | None:
        reusable = {
            "queued", "preparing", "running", "aggregating", "comparing", "completed"
        }
        return next(
            (
                run for run in self.runs.values()
                if run.run_fingerprint.run_fingerprint_hash == run_fingerprint_hash
                and run.status in reusable
            ),
            None,
        )

    def list_trial_runs(self, trial_group_id: str) -> list[EvaluationRun]:
        return sorted(
            (run for run in self.runs.values() if run.trial_group_id == trial_group_id),
            key=lambda run: run.repeat_index if run.repeat_index is not None else -1,
        )

    def update_run(self, run: EvaluationRun) -> None:
        with self._lock:
            current = self.get_run(run.run_id)
            if current.status in TERMINAL_RUN_STATUSES and current != run:
                raise EvaluationStoreError("evaluation_run_immutable", run.run_id)
            if run.status != current.status and run.status not in RUN_TRANSITIONS.get(current.status, set()):
                raise EvaluationStoreError(
                    "evaluation_run_transition_invalid", f"{current.status}->{run.status}"
                )
            self.runs[run.run_id] = run

    def save_case_result(self, result: CaseResult) -> None:
        self._immutable_put(self.case_results, result.result_id, result, "evaluation_case_result_immutable")

    def list_case_results(self, run_id: str) -> list[CaseResult]:
        return sorted(
            (item for item in self.case_results.values() if item.evaluation_run_id == run_id),
            key=lambda item: item.case_id,
        )

    def save_metric_definition(self, definition: MetricDefinition) -> None:
        self._immutable_put(
            self.metric_definitions, definition.metric_definition_id, definition,
            "evaluation_metric_definition_immutable",
        )

    def get_metric_definition(self, metric_definition_id: str) -> MetricDefinition:
        try:
            return self.metric_definitions[metric_definition_id]
        except KeyError as exc:
            raise EvaluationStoreError("metric_definition_not_found", metric_definition_id) from exc

    def save_metric_result(self, result: MetricResult) -> None:
        self._immutable_put(self.metric_results, result.metric_result_id, result, "metric_result_immutable")

    def list_metric_results(self, run_id: str) -> list[MetricResult]:
        return [item for item in self.metric_results.values() if item.evaluation_run_id == run_id]

    def save_comparison(self, comparison: RegressionComparison) -> None:
        self._immutable_put(self.comparisons, comparison.comparison_id, comparison, "comparison_immutable")

    def save_gate_config(self, config: RegressionGateConfig) -> None:
        self._immutable_put(self.gate_configs, config.gate_config_version, config, "gate_config_immutable")

    def get_gate_config(self, version: str) -> RegressionGateConfig:
        try:
            return self.gate_configs[version]
        except KeyError as exc:
            raise EvaluationStoreError("gate_config_not_found", version) from exc

    def save_gate(self, gate: RegressionGate) -> None:
        self._immutable_put(self.gates, gate.gate_id, gate, "regression_gate_immutable")

    def promote_baseline(self, binding: EvaluationBaselineBinding) -> EvaluationBaselineBinding:
        with self._lock:
            run = self.get_run(binding.baseline_run_id)
            subject = self.get_subject(binding.subject_id)
            if run.status != "completed" or not run.complete:
                raise EvaluationStoreError("baseline_run_incomplete", run.run_id)
            if run.subject_id != binding.subject_id or run.dataset_version_id != binding.dataset_version_id:
                raise EvaluationStoreError("baseline_binding_identity_mismatch")
            try:
                require_formal_baseline_subject(subject)
            except EvaluationSubjectError as exc:
                raise EvaluationStoreError(str(exc)) from exc
            for key, existing in list(self.baseline_bindings.items()):
                same_scope = (
                    existing.dataset_version_id == binding.dataset_version_id
                    and existing.component == binding.component
                    and existing.evaluation_mode == binding.evaluation_mode
                    and existing.gate_config_version == binding.gate_config_version
                )
                if same_scope and existing.status == "active":
                    self.baseline_bindings[key] = existing.model_copy(update={"status": "superseded"})
            self.baseline_bindings[binding.baseline_binding_id] = binding
            return binding

    def get_baseline_binding(self, binding_id: str) -> EvaluationBaselineBinding:
        try:
            return self.baseline_bindings[binding_id]
        except KeyError as exc:
            raise EvaluationStoreError("evaluation_baseline_not_found", binding_id) from exc

    def save_bad_case(self, bad_case: BadCase) -> None:
        with self._lock:
            existing = self.bad_cases.get(bad_case.bad_case_id)
            if existing:
                if existing == bad_case:
                    return
                if bad_case.revision != existing.revision + 1:
                    raise EvaluationStoreError("bad_case_conflict", bad_case.bad_case_id)
            self.bad_cases[bad_case.bad_case_id] = bad_case

    def get_bad_case(self, bad_case_id: str) -> BadCase:
        try:
            return self.bad_cases[bad_case_id]
        except KeyError as exc:
            raise EvaluationStoreError("bad_case_not_found", bad_case_id) from exc

    def find_bad_case_by_fingerprint(self, fingerprint: str) -> BadCase | None:
        return next((item for item in self.bad_cases.values() if item.fingerprint == fingerprint), None)

    def append_bad_case_occurrence(self, occurrence: BadCaseOccurrence) -> None:
        self._immutable_put(
            self.bad_case_occurrences, occurrence.occurrence_id, occurrence,
            "bad_case_occurrence_immutable",
        )

    def get_bad_case_occurrence(self, occurrence_id: str) -> BadCaseOccurrence | None:
        return self.bad_case_occurrences.get(occurrence_id)

    def append_bad_case_event(self, event: BadCaseEvent) -> None:
        self._immutable_put(self.bad_case_events, event.event_id, event, "bad_case_event_immutable")

    def save_bad_case_verification(self, verification: BadCaseVerification) -> None:
        self._immutable_put(
            self.bad_case_verifications, verification.verification_id, verification,
            "bad_case_verification_immutable",
        )

    def save_promotion(self, promotion: RegressionCasePromotion) -> None:
        self._immutable_put(self.promotions, promotion.promotion_id, promotion, "promotion_immutable")

    def list_promotions(self, bad_case_id: str) -> list[RegressionCasePromotion]:
        return [item for item in self.promotions.values() if item.bad_case_id == bad_case_id]

    def save_replay_manifest(self, manifest: ReplayManifest) -> None:
        self._immutable_put(
            self.replay_manifests, manifest.replay_manifest_id, manifest,
            "replay_manifest_immutable",
        )

    def get_replay_manifest(self, replay_manifest_id: str) -> ReplayManifest:
        try:
            return self.replay_manifests[replay_manifest_id]
        except KeyError as exc:
            raise EvaluationStoreError("replay_manifest_not_found", replay_manifest_id) from exc
