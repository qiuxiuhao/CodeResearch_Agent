from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.app.evaluation.adapter import EvaluationExecutionContext
from backend.app.evaluation.adapters import (
    AgentEvaluationAdapter,
    AlignmentEvaluationAdapter,
    AnswerEvaluationAdapter,
    IndexEvaluationAdapter,
    ObservabilityEvaluationAdapter,
    RetrievalEvaluationAdapter,
)
from backend.app.evaluation.artifact_resolver import (
    ControlledArtifactResolver,
    EvaluationAccessContext,
)
from backend.app.evaluation.bad_case_analyzer import BadCaseAnalyzer
from backend.app.evaluation.metric_engine import MetricEngine, default_metric_definitions
from backend.app.evaluation.schemas import (
    EvaluationPlan,
    EvaluationProvenance,
    EvaluationRun,
    EvaluationRunCreateRequest,
    EvaluationRunFingerprint,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id
from backend.app.evaluation.store_protocol import EvaluationStoreError, EvaluationStoreProtocol


ContextFactory = Callable[[EvaluationRun, list], EvaluationExecutionContext]


class EvaluationService:
    def __init__(
        self,
        store: EvaluationStoreProtocol,
        *,
        context_factory: ContextFactory | None = None,
        fixture_root: str = "evaluation",
    ) -> None:
        self.store = store
        self.context_factory = context_factory
        self.live_executor_configured = context_factory is not None
        self.fixture_root = fixture_root
        self.metric_engine = MetricEngine()
        self.bad_case_analyzer = BadCaseAnalyzer(store)
        self.adapters = {
            "index": IndexEvaluationAdapter(),
            "retrieval": RetrievalEvaluationAdapter(),
            "agent": AgentEvaluationAdapter(),
            "alignment": AlignmentEvaluationAdapter(),
            "answer": AnswerEvaluationAdapter(),
            "observability": ObservabilityEvaluationAdapter(),
        }

    def prepare_run(
        self,
        request: EvaluationRunCreateRequest,
        *,
        caller_scope_hash: str,
        repeat_index: int | None = None,
    ) -> EvaluationRun:
        version = self.store.get_dataset_version(request.dataset_version_id)
        if version.status != "frozen":
            raise EvaluationStoreError("dataset_not_frozen", request.dataset_version_id)
        subject = self.store.get_subject(request.subject_id)
        environment = self.store.get_environment(request.environment_id)
        cases = self.store.list_cases(request.dataset_version_id, request.case_ids or None)
        cases = [case for case in cases if case.component in request.components]
        if not cases:
            raise EvaluationStoreError("evaluation_case_not_found")
        metric_definitions = [
            item for item in default_metric_definitions()
            if item.component in request.components
            and (not request.metric_definition_ids or item.metric_definition_id in request.metric_definition_ids)
        ]
        for definition in metric_definitions:
            self.store.save_metric_definition(definition)
        case_ids = [case.case_id for case in cases]
        adapter_versions = {
            component: request.adapter_versions.get(component, self.adapters[component].adapter_version)
            for component in request.components
        }
        case_set_hash = stable_hash(case_ids)
        metric_hash = stable_hash([item.model_dump(mode="json") for item in metric_definitions])
        adapter_hash = stable_hash(adapter_versions)
        fingerprint_payload = {
            "dataset_version_id": version.dataset_version_id,
            "case_set_hash": case_set_hash,
            "gold_hash": version.gold_hash,
            "subject_id": subject.subject_id,
            "metric_definition_hash": metric_hash,
            "adapter_profile_hash": adapter_hash,
            "adapter_major_hash": stable_hash(
                {key: value.split(".", 1)[0] for key, value in adapter_versions.items()}
            ),
            "fixture_hash": version.fixture_hash,
            "execution_mode": request.mode,
            "environment_hash": environment.environment_hash,
            "random_seed": request.random_seed,
        }
        fingerprint = EvaluationRunFingerprint(
            **fingerprint_payload,
            run_fingerprint_hash=stable_hash(fingerprint_payload),
        )
        if request.retry_of_run_id is None and request.live_trial is None:
            reusable = self.store.find_reusable_run(fingerprint.run_fingerprint_hash)
            if reusable is not None:
                return reusable
        attempt = 1
        if request.retry_of_run_id:
            parent = self.store.get_run(request.retry_of_run_id)
            if parent.status not in {"failed", "cancelled", "partial"}:
                raise EvaluationStoreError("evaluation_retry_not_allowed")
            attempt = parent.attempt_number + 1
        plan_payload = {
            "dataset_version_id": version.dataset_version_id,
            "subject_id": subject.subject_id,
            "mode": request.mode,
            "case_ids": case_ids,
            "adapter_versions": adapter_versions,
            "metric_definition_ids": [item.metric_definition_id for item in metric_definitions],
            "baseline_binding_id": request.baseline_binding_id,
            "gate_config_version": request.gate_config_version,
            "case_concurrency": request.case_concurrency,
            "provider_concurrency": request.provider_concurrency,
            "random_seed": request.random_seed,
            "live_trial": request.live_trial.model_dump(mode="json") if request.live_trial else None,
        }
        now = datetime.now(UTC)
        provenance = EvaluationProvenance(
            subject_id=subject.subject_id,
            dataset_version_id=version.dataset_version_id,
            fixture_version=cases[0].fixture.fixture_version,
            adapter_profile_hash=adapter_hash,
            metric_definition_hash=metric_hash,
            created_at=now,
        )
        plan = EvaluationPlan(
            plan_id=stable_id("eval_plan", plan_payload),
            dataset_version_id=version.dataset_version_id,
            subject_id=subject.subject_id,
            mode=request.mode,
            components=request.components,
            adapter_versions=adapter_versions,
            metric_definition_ids=[item.metric_definition_id for item in metric_definitions],
            case_ids=case_ids,
            baseline_binding_id=request.baseline_binding_id,
            gate_config_version=request.gate_config_version,
            frozen_config_hash=stable_hash(plan_payload),
            case_concurrency=request.case_concurrency,
            provider_concurrency=request.provider_concurrency,
            provider_budget=request.provider_budget,
            external_model_consent=request.external_model_consent,
            random_seed=request.random_seed,
            live_trial=request.live_trial,
            provenance=provenance,
        )
        effective_repeat_index = (
            repeat_index if request.live_trial is not None else None
        )
        run_payload = [
            fingerprint.run_fingerprint_hash,
            attempt,
            request.retry_of_run_id,
            effective_repeat_index,
        ]
        run = EvaluationRun(
            run_id=stable_id("evaluation_run", run_payload),
            plan_id=plan.plan_id,
            dataset_version_id=version.dataset_version_id,
            subject_id=subject.subject_id,
            mode=request.mode,
            status="queued",
            run_fingerprint=fingerprint,
            environment_id=environment.environment_id,
            trial_group_id=request.live_trial.trial_group_id if request.live_trial else None,
            repeat_index=effective_repeat_index,
            repeat_count=request.live_trial.repeat_count if request.live_trial else None,
            temperature=request.live_trial.temperature if request.live_trial else None,
            seed=request.live_trial.seed if request.live_trial else request.random_seed,
            attempt_number=attempt,
            retry_of_run_id=request.retry_of_run_id,
            case_counts={"total": len(cases), "completed": 0, "failed": 0},
            provenance=provenance,
            created_at=now,
            updated_at=now,
        )
        try:
            existing_plan = self.store.get_plan(plan.plan_id)
            if existing_plan.frozen_config_hash != plan.frozen_config_hash:
                raise EvaluationStoreError("evaluation_plan_conflict", plan.plan_id)
            plan = existing_plan
        except EvaluationStoreError as exc:
            if exc.error_code != "evaluation_plan_not_found":
                raise
            self.store.save_plan(plan)
        self.store.save_run(run, caller_scope_hash=caller_scope_hash)
        return run

    async def process_run(self, run_id: str) -> EvaluationRun:
        run = self.store.get_run(run_id)
        plan = self.store.get_plan(run.plan_id)
        cases = self.store.list_cases(run.dataset_version_id, plan.case_ids)
        if run.status == "queued":
            run = self._transition(run, "preparing")
        if run.cancel_requested:
            return self._terminal(run, "cancelled", complete=False, reasons=["cancel_requested"])
        if run.status == "preparing":
            run = self._transition(run, "running")
        context = self._context(run, cases)
        execution_limit = plan.case_concurrency
        if plan.mode == "live_experiment":
            execution_limit = min(plan.case_concurrency, max(1, plan.provider_concurrency))
        semaphore = asyncio.Semaphore(execution_limit)

        async def execute(case):
            async with semaphore:
                latest = self.store.get_run(run_id)
                if latest.cancel_requested:
                    return None
                result = await self.adapters[case.component].execute(case, context)
                self.store.save_case_result(result)
                return result

        existing_results = {item.case_id: item for item in self.store.list_case_results(run_id)}
        pending_cases = [case for case in cases if case.case_id not in existing_results]
        new_results = [
            item for item in await asyncio.gather(*(execute(case) for case in pending_cases)) if item
        ] if run.status == "running" else []
        results = list(existing_results.values()) + new_results
        latest = self.store.get_run(run_id)
        if latest.cancel_requested:
            return self._terminal(latest, "cancelled", complete=False, reasons=["cancel_requested"])
        run = self._transition(latest, "aggregating") if latest.status == "running" else latest
        if run.status not in {"aggregating", "comparing"}:
            raise EvaluationStoreError("evaluation_run_recovery_state_invalid", run.status)
        metrics = self.metric_engine.compute(
            evaluation_run_id=run_id, cases=cases, results=results
        )
        for metric in metrics:
            self.store.save_metric_result(metric)
        by_case = {case.case_id: case for case in cases}
        for result in results:
            if result.evaluation_outcome != "passed" or not result.complete:
                self.bad_case_analyzer.analyze(
                    case=by_case[result.case_id], result=result, subject_id=run.subject_id
                )
        complete = len(results) == len(cases) and all(
            item.complete
            and item.execution_status == "completed"
            and item.evaluation_outcome in {"passed", "failed"}
            for item in results
        )
        counts = {
            "total": len(cases),
            "completed": sum(item.execution_status == "completed" for item in results),
            "failed": sum(item.execution_status == "error" for item in results),
            "passed": sum(item.evaluation_outcome == "passed" for item in results),
            "quality_failed": sum(item.evaluation_outcome == "failed" for item in results),
        }
        run = run.model_copy(update={"case_counts": counts})
        return self._terminal(
            run,
            "completed" if complete else "partial",
            complete=complete,
            reasons=[] if complete else ["case_result_incomplete"],
        )

    def _context(self, run: EvaluationRun, cases: list) -> EvaluationExecutionContext:
        if self.context_factory is not None:
            return self.context_factory(run, cases)
        resolver = ControlledArtifactResolver(fixture_root=self.fixture_root)
        refs: dict[str, Any] = {}
        for case in cases:
            for ref_id in case.input_artifact_ref_ids:
                refs[ref_id] = self.store.get_artifact_ref(ref_id)
        return EvaluationExecutionContext(
            evaluation_run_id=run.run_id,
            resolver=resolver,
            access_context=EvaluationAccessContext("evaluation-coordinator", local_admin=True),
            artifact_refs=refs,
        )

    def _transition(self, run: EvaluationRun, status: str) -> EvaluationRun:
        updated = run.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})
        self.store.update_run(updated)
        return updated

    def _terminal(
        self, run: EvaluationRun, status: str, *, complete: bool, reasons: list[str]
    ) -> EvaluationRun:
        now = datetime.now(UTC)
        updated = run.model_copy(
            update={
                "status": status,
                "complete": complete,
                "incomplete_reason_codes": reasons,
                "updated_at": now,
                "finished_at": now,
            }
        )
        self.store.update_run(updated)
        return updated
