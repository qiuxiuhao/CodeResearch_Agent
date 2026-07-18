from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.agents.research.argument_resolver import (
    ResolvedStepArguments,
    StepArgumentResolver,
    semantic_tool_call_key,
    step_execution_id,
)
from backend.app.agents.research.budget import AgentBudget
from backend.app.agents.research.schemas import PlanStep, PlanStepRuntime, ToolObservation
from backend.app.agents.research.tool_registry import ToolExecutionContext, ToolRegistry
from backend.app.observability.context import start_span_or_root


_TOOL_SPAN_INDEX: dict[str, tuple[str, str]] = {}


class AgentBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StepExecutionOutcome:
    observation: ToolObservation
    runtime: PlanStepRuntime
    resolved: ResolvedStepArguments
    actual_tool_calls: int
    reused_tool_calls: int
    tool_failures: int


class ResearchExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        resolver: StepArgumentResolver | None = None,
        budget: AgentBudget | None = None,
    ) -> None:
        self.registry = registry
        self.resolver = resolver or StepArgumentResolver(registry)
        self.budget = budget or AgentBudget()

    def resolve(
        self,
        *,
        step: PlanStep,
        plan_version: str,
        observations: list[ToolObservation],
    ) -> ResolvedStepArguments:
        return self.resolver.resolve(step, observations, plan_version=plan_version)

    async def execute(
        self,
        *,
        run_id: str,
        repo_id: str,
        index_version_id: str,
        plan_version: str,
        step: PlanStep,
        resolved: ResolvedStepArguments,
        observations: list[ToolObservation],
        state: dict,
        cancel_check=None,
        trace_id: str | None = None,
    ) -> StepExecutionOutcome:
        execution_id = step_execution_id(run_id, plan_version, step.step_id)
        call_key = semantic_tool_call_key(
            run_id=run_id,
            repo_id=repo_id,
            index_version_id=index_version_id,
            tool_name=step.tool_name,
            canonical_arguments_json=resolved.canonical_json,
        )
        reusable = next(
            (
                item
                for item in reversed(observations)
                if item.tool_call_key == call_key and item.status == "success"
            ),
            None,
        )
        started = datetime.now(UTC)
        if reusable is not None:
            reuse_span = start_span_or_root(
                operation="tool.reuse",
                trace_type="research_agent",
                component="tool",
                run_id=run_id,
                repo_id=repo_id,
                index_version_id=index_version_id,
                attributes={"cra.tool.name": step.tool_name, "cra.tool.reused": True},
            )
            async with reuse_span:
                source_span = _TOOL_SPAN_INDEX.get(reusable.observation_id)
                if source_span:
                    reuse_span.link(
                        source_span[0], linked_span_id=source_span[1], relation="reused_from"
                    )
                observation = reusable.model_copy(update={
                    "observation_id": f"obs_{uuid4().hex}",
                    "step_id": step.step_id,
                    "plan_version": plan_version,
                    "step_execution_id": execution_id,
                    "reused": True,
                    "reused_observation_id": reusable.observation_id,
                    "reused_from_plan_version": reusable.plan_version,
                    "latency_ms": 0.0,
                })
                return StepExecutionOutcome(
                    observation=observation,
                    runtime=_runtime(step, plan_version, execution_id, observation, started),
                    resolved=resolved,
                    actual_tool_calls=0,
                    reused_tool_calls=1,
                    tool_failures=0,
                )
        if not self.budget.can_call_tool(state):
            raise AgentBudgetExceeded("tool_call_budget_exhausted")
        invocation = await self.registry.invoke(
            step.tool_name,
            resolved.model,
            ToolExecutionContext(
                run_id=run_id,
                repo_id=repo_id,
                index_version_id=index_version_id,
                trace_id=trace_id,
                cancel_check=cancel_check,
            ),
        )
        result = invocation.result
        observation = ToolObservation(
            observation_id=f"obs_{uuid4().hex}",
            step_id=step.step_id,
            plan_version=plan_version,
            tool_name=step.tool_name,
            resolved_arguments_hash=resolved.arguments_hash,
            tool_call_key=call_key,
            step_execution_id=execution_id,
            status=invocation.status,
            entity_ids=result.entity_ids,
            chunk_ids=result.chunk_ids,
            edge_ids=result.edge_ids,
            evidence_ids=result.evidence_ids,
            summary=result.summary,
            result_count=result.result_count,
            warnings=result.warnings,
            latency_ms=invocation.latency_ms,
            error=invocation.error,
        )
        if invocation.trace_id and invocation.span_id:
            if len(_TOOL_SPAN_INDEX) >= 4_096:
                _TOOL_SPAN_INDEX.pop(next(iter(_TOOL_SPAN_INDEX)))
            _TOOL_SPAN_INDEX[observation.observation_id] = (
                invocation.trace_id, invocation.span_id
            )
        return StepExecutionOutcome(
            observation=observation,
            runtime=_runtime(step, plan_version, execution_id, observation, started),
            resolved=resolved,
            actual_tool_calls=1,
            reused_tool_calls=0,
            tool_failures=int(invocation.status in {"failed", "timeout"}),
        )


def _runtime(
    step: PlanStep,
    plan_version: str,
    execution_id: str,
    observation: ToolObservation,
    started: datetime,
) -> PlanStepRuntime:
    status = observation.status if observation.status in {"success", "empty", "failed"} else "failed"
    return PlanStepRuntime(
        step_id=step.step_id,
        plan_version=plan_version,
        status=status,
        step_execution_id=execution_id,
        observation_id=observation.observation_id,
        started_at=started,
        finished_at=datetime.now(UTC),
        error_code=observation.error.error_code if observation.error else None,
    )
