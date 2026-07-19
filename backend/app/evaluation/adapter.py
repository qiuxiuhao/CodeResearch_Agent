from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Awaitable, Callable, Protocol

from pydantic import TypeAdapter

from backend.app.evaluation.artifact_resolver import (
    ArtifactResolverError,
    EvaluationAccessContext,
    EvaluationArtifactResolver,
)
from backend.app.evaluation.schemas import (
    CaseResult,
    EvaluationCase,
    EvaluationComponent,
    EvaluationOutcome,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id


OutcomeExecutor = Callable[[EvaluationCase], EvaluationOutcome | Awaitable[EvaluationOutcome]]


@dataclass(slots=True)
class EvaluationExecutionContext:
    evaluation_run_id: str
    resolver: EvaluationArtifactResolver
    access_context: EvaluationAccessContext
    artifact_refs: dict[str, object] = field(default_factory=dict)
    resolved_artifacts: dict[str, bytes] = field(default_factory=dict)
    fixed_outcomes: dict[str, EvaluationOutcome] = field(default_factory=dict)
    executors: dict[str, OutcomeExecutor] = field(default_factory=dict)


class EvaluationAdapter(Protocol):
    component: EvaluationComponent
    adapter_version: str

    async def prepare(self, case: EvaluationCase, context: EvaluationExecutionContext) -> None: ...
    async def execute(self, case: EvaluationCase, context: EvaluationExecutionContext) -> CaseResult: ...


class BaseEvaluationAdapter:
    component: EvaluationComponent
    adapter_version = "1.0.0"

    async def prepare(self, case: EvaluationCase, context: EvaluationExecutionContext) -> None:
        if case.component != self.component:
            raise ValueError("evaluation_adapter_component_mismatch")
        for ref_id in case.input_artifact_ref_ids:
            ref = context.artifact_refs.get(ref_id)
            if ref is None:
                raise ValueError("evaluation_input_artifact_missing")
            resolved = context.resolver.resolve(ref, context.access_context)  # type: ignore[arg-type]
            context.resolved_artifacts[ref_id] = resolved.content

    async def execute(self, case: EvaluationCase, context: EvaluationExecutionContext) -> CaseResult:
        started_at = datetime.now(UTC)
        started = perf_counter_ns()
        try:
            await self.prepare(case, context)
            outcome = context.fixed_outcomes.get(case.case_id)
            if outcome is None:
                executor = context.executors.get(self.component)
                if executor is not None:
                    outcome = executor(case)
                    if hasattr(outcome, "__await__"):
                        outcome = await outcome  # type: ignore[misc]
                else:
                    outcome = self._artifact_outcome(case, context)
                    if outcome is None:
                        return self._not_evaluable(case, context, started_at, started)
            quality_failure_codes = self.quality_failures(case, outcome)
            evaluation_outcome = "failed" if quality_failure_codes else "passed"
            return self._result(
                case, context, started_at, started,
                execution_status="completed",
                evaluation_outcome=evaluation_outcome,
                outcome=outcome,
                complete=True,
                quality_failure_codes=quality_failure_codes,
            )
        except ArtifactResolverError as exc:
            return self._result(
                case, context, started_at, started,
                execution_status="completed",
                evaluation_outcome="indeterminate",
                outcome=None,
                complete=False,
                incomplete_reason_codes=[exc.error_code],
            )
        except Exception as exc:
            return self._result(
                case, context, started_at, started,
                execution_status="error",
                evaluation_outcome=None,
                outcome=None,
                complete=False,
                incomplete_reason_codes=["execution_error"],
                execution_error_code=getattr(exc, "error_code", "evaluation_adapter_error"),
            )

    def quality_failures(self, case: EvaluationCase, outcome: EvaluationOutcome) -> list[str]:
        raise NotImplementedError

    def _artifact_outcome(
        self, case: EvaluationCase, context: EvaluationExecutionContext
    ) -> EvaluationOutcome | None:
        adapter = TypeAdapter(EvaluationOutcome)
        for ref_id in case.input_artifact_ref_ids:
            ref = context.artifact_refs.get(ref_id)
            if getattr(ref, "artifact_type", None) != "prediction":
                continue
            content = context.resolved_artifacts.get(ref_id)
            if content is None:
                continue
            outcome = adapter.validate_json(content)
            if outcome.component != self.component:
                raise ValueError("evaluation_prediction_component_mismatch")
            return outcome
        return None

    def _not_evaluable(
        self, case: EvaluationCase, context: EvaluationExecutionContext,
        started_at: datetime, started: int,
    ) -> CaseResult:
        return self._result(
            case, context, started_at, started,
            execution_status="completed", evaluation_outcome="not_evaluable",
            outcome=None, complete=True,
        )

    def _result(
        self,
        case: EvaluationCase,
        context: EvaluationExecutionContext,
        started_at: datetime,
        started_ns: int,
        *,
        execution_status: str,
        evaluation_outcome: str | None,
        outcome: EvaluationOutcome | None,
        complete: bool,
        incomplete_reason_codes: list[str] | None = None,
        execution_error_code: str | None = None,
        quality_failure_codes: list[str] | None = None,
    ) -> CaseResult:
        finished_at = datetime.now(UTC)
        payload = outcome.model_dump(mode="json") if outcome else None
        return CaseResult(
            result_id=stable_id("result", [context.evaluation_run_id, case.case_id]),
            evaluation_run_id=context.evaluation_run_id,
            case_id=case.case_id,
            component=case.component,
            execution_status=execution_status,
            evaluation_outcome=evaluation_outcome,
            complete=complete,
            incomplete_reason_codes=incomplete_reason_codes or [],
            execution_error_code=execution_error_code,
            quality_failure_codes=quality_failure_codes or [],
            outcome=outcome,
            latency_ms=(perf_counter_ns() - started_ns) / 1_000_000,
            token_usage={},
            content_hash=stable_hash(payload),
            started_at=started_at,
            finished_at=finished_at,
        )
