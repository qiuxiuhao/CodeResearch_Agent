from __future__ import annotations

import hashlib
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.agents.research.answer_pipeline import (
    AgentCitationValidator,
    AnswerFinalizer,
    ClaimVerifier,
    ConsentAwareAnswerGenerator,
    EvidenceFirstAnswerGenerator,
)
from backend.app.agents.research.argument_resolver import canonical_arguments, step_execution_id
from backend.app.agents.research.budget import AgentBudget
from backend.app.agents.research.context_service import ResearchContextService
from backend.app.agents.research.evidence_checker import EvidenceSufficiencyChecker
from backend.app.agents.research.executor import AgentBudgetExceeded, ResearchExecutor
from backend.app.agents.research.plan_validator import PlanValidationError, PlanValidator
from backend.app.agents.research.planner import RuleBasedPlanner
from backend.app.agents.research.router import RuleBasedResearchRouter
from backend.app.agents.research.schemas import (
    AgentError,
    AgentResearchAnswer,
    PlanStep,
    PlanStepRuntime,
    ResearchPlan,
)
from backend.app.agents.research.state import ResearchState
from backend.app.agents.research.tool_registry import ToolRegistry
from backend.app.persistence.research_run_store import ResearchRunStore


GRAPH_VERSION = "1.0"
STATE_SCHEMA_VERSION = "1.0"


@dataclass(slots=True)
class ResearchGraphRuntime:
    registry: ToolRegistry
    context_service: ResearchContextService
    run_store: ResearchRunStore | None = None
    router: RuleBasedResearchRouter | None = None
    planner: RuleBasedPlanner | None = None
    plan_validator: PlanValidator | None = None
    executor: ResearchExecutor | None = None
    evidence_checker: EvidenceSufficiencyChecker | None = None
    budget: AgentBudget | None = None
    answer_generator: ConsentAwareAnswerGenerator | EvidenceFirstAnswerGenerator | None = None
    citation_validator: AgentCitationValidator | None = None
    claim_verifier: ClaimVerifier | None = None
    finalizer: AnswerFinalizer | None = None

    def __post_init__(self) -> None:
        self.router = self.router or RuleBasedResearchRouter()
        self.planner = self.planner or RuleBasedPlanner()
        self.budget = self.budget or AgentBudget()
        self.plan_validator = self.plan_validator or PlanValidator(self.registry, self.budget)
        self.executor = self.executor or ResearchExecutor(self.registry, budget=self.budget)
        self.evidence_checker = self.evidence_checker or EvidenceSufficiencyChecker()
        if self.answer_generator is None:
            self.answer_generator = ConsentAwareAnswerGenerator(None)
        elif isinstance(self.answer_generator, EvidenceFirstAnswerGenerator):
            self.answer_generator = ConsentAwareAnswerGenerator(None, self.answer_generator)
        self.citation_validator = self.citation_validator or AgentCitationValidator()
        self.claim_verifier = self.claim_verifier or ClaimVerifier()
        self.finalizer = self.finalizer or AnswerFinalizer()

    def cancelled(self, state: ResearchState) -> bool:
        if state.get("cancel_requested"):
            return True
        return bool(self.run_store and self.run_store.is_cancel_requested(state["run_id"]))


def initial_research_state(
    *,
    run: dict,
    request: dict,
) -> ResearchState:
    now = datetime.now(UTC)
    state = ResearchState(
        state_schema_version=STATE_SCHEMA_VERSION,
        graph_version=GRAPH_VERSION,
        run_id=run["run_id"],
        thread_id=run["thread_id"],
        parent_run_id=run.get("parent_run_id"),
        continued_from_run_id=run.get("continued_from_run_id"),
        repo_id=run["repo_id"],
        index_version_id=run["index_version_id"],
        query=request["query"],
        route="direct",
        route_reason=[],
        direct_escalated_to_planned=False,
        plan=None,
        pending_plan=None,
        plan_history_ids=[],
        current_step_index=0,
        step_runtime=[],
        resolved_arguments={},
        step_resolution_failed=False,
        observations=[],
        evidence_ids=list(request.get("seed_evidence_ids", [])),
        seed_evidence_ids=list(request.get("seed_evidence_ids", [])),
        entity_ids=[],
        evidence_sufficient=False,
        missing_evidence=[],
        answer_enabled=bool(request.get("answer_enabled", True)),
        external_text_consent=bool(request.get("external_text_consent", False)),
        tool_call_count=0,
        tool_reuse_count=0,
        replan_count=0,
        tool_failure_count=0,
        token_usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        status="queued",
        errors=[],
        cancel_requested=False,
        resume_count=int(run.get("resume_count", 0)),
        created_at=_as_datetime(run.get("created_at"), now),
        updated_at=now,
    )
    if request.get("query_type"):
        state["query_type"] = request["query_type"]
    return state


def build_research_agent_graph(runtime: ResearchGraphRuntime, *, checkpointer=None):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ResearchState)

    async def route_query(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        decision = runtime.router.route(state["query"], explicit_type=state.get("query_type"))
        return {
            "query_type": decision.query_type,
            "route": decision.route,
            "route_reason": decision.reasons,
            "status": "routing",
            "updated_at": datetime.now(UTC),
        }

    async def direct_retrieve(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        step = PlanStep(
            step_id="direct_retrieve",
            ordinal=0,
            goal="Retrieve direct evidence.",
            tool_name="search_hybrid",
            literal_arguments={
                "query": state["query"], "query_type": state["query_type"], "top_k": 10,
            },
            success_criteria=["Return direct repository evidence."],
        )
        return await _execute_step(runtime, state, step, "direct") | {"status": "retrieving"}

    async def create_plan(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        version = int(state.get("replan_count", 0)) + 1
        plan = runtime.planner.create_plan(
            query=state["query"], query_type=state["query_type"], plan_version=version,
            external_text_consent=state.get("external_text_consent", False),
        )
        plan = plan.model_copy(update={
            "plan_id": f"plan_{_digest(state['run_id'], plan.plan_id)[:24]}"
        })
        if runtime.run_store:
            runtime.run_store.save_plan(
                state["run_id"], plan,
                planner_request_hash=_digest(state["query"], state["query_type"], str(version)),
                replaced_reason="replan" if state.get("plan") else None,
            )
        history = [*state.get("plan_history_ids", [])]
        if plan.plan_id not in history:
            history.append(plan.plan_id)
        return {
            "pending_plan": plan,
            "plan_history_ids": history,
            "route": "planned",
            "status": "planning" if not state.get("plan") else "replanning",
            "updated_at": datetime.now(UTC),
        }

    async def validate_plan(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        pending = state.get("pending_plan")
        if pending is None:
            return _failure("plan_missing", "No pending plan is available.")
        try:
            plan = runtime.plan_validator.validate(pending)
        except PlanValidationError as exc:
            return _failure(exc.error_code, str(exc))
        return {
            "plan": plan,
            "pending_plan": None,
            "current_step_index": 0,
            "step_runtime": [
                *[
                    item for item in state.get("step_runtime", [])
                    if item.plan_version != plan.plan_version
                ],
                *[
                    PlanStepRuntime(
                        step_id=step.step_id, plan_version=plan.plan_version, status="pending"
                    )
                    for step in plan.steps
                ],
            ],
            "status": "planning",
            "updated_at": datetime.now(UTC),
        }

    async def resolve_step_arguments(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        plan, step = _current_step(state)
        if step is None:
            return _failure("plan_step_missing", "No executable plan step is available.")
        try:
            resolved = runtime.executor.resolve(
                step=step,
                plan_version=plan.plan_version,
                observations=state.get("observations", []),
            )
        except Exception as exc:
            error_code = getattr(exc, "error_code", "step_argument_resolution_failed")
            return _failed_step_update(state, step, plan.plan_version, error_code, str(exc))
        runtimes = _replace_runtime(state, PlanStepRuntime(
            step_id=step.step_id,
            plan_version=plan.plan_version,
            status="resolving",
        ))
        return {
            "resolved_arguments": resolved.model.model_dump(mode="json"),
            "step_resolution_failed": False,
            "step_runtime": runtimes,
            "status": "executing",
            "updated_at": datetime.now(UTC),
        }

    async def execute_step(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        plan, step = _current_step(state)
        if step is None:
            return _failure("plan_step_missing", "No executable plan step is available.")
        spec = runtime.registry.get(step.tool_name)
        model = spec.input_model.model_validate(state.get("resolved_arguments", {}))
        canonical = canonical_arguments(model.model_dump(mode="json"))
        resolved = runtime.executor.resolve(
            step=step,
            plan_version=plan.plan_version,
            observations=state.get("observations", []),
        )
        if resolved.canonical_json != canonical:
            return _failure("resolved_arguments_changed", "Resolved arguments changed before execution.")
        try:
            return await _execute_step(runtime, state, step, plan.plan_version, resolved=resolved)
        except AgentBudgetExceeded as exc:
            return {**_failure(str(exc), str(exc)), "stop_reason": str(exc)}

    async def mark_step_running(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        plan, step = _current_step(state)
        if step is None:
            return _failure("plan_step_missing", "No executable plan step is available.")
        existing = next((
            item for item in state.get("step_runtime", [])
            if item.step_id == step.step_id and item.plan_version == plan.plan_version
        ), None)
        current = PlanStepRuntime(
            step_id=step.step_id,
            plan_version=plan.plan_version,
            status="running",
            step_execution_id=step_execution_id(state["run_id"], plan.plan_version, step.step_id),
            started_at=existing.started_at if existing and existing.started_at else datetime.now(UTC),
        )
        return {
            "step_runtime": _replace_runtime(state, current),
            "status": "executing",
            "updated_at": datetime.now(UTC),
        }

    async def assess_evidence(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        plan = state.get("plan")
        has_remaining = bool(plan and state.get("current_step_index", 0) < len(plan.steps))
        assessment = runtime.evidence_checker.assess(
            query_type=state["query_type"],
            route=state["route"],
            observations=state.get("observations", []),
            has_remaining_steps=has_remaining,
            direct_escalated_to_planned=state.get("direct_escalated_to_planned", False),
            can_replan=runtime.budget.can_replan(state),
        )
        update = {
            "evidence_assessment": assessment,
            "evidence_sufficient": assessment.sufficient,
            "missing_evidence": assessment.missing_evidence,
            "evidence_ids": _unique([*state.get("evidence_ids", []), *assessment.covered_evidence_ids]),
            "entity_ids": _unique([*state.get("entity_ids", []), *assessment.covered_entity_ids]),
            "status": "assessing",
            "updated_at": datetime.now(UTC),
        }
        if assessment.next_action == "escalate_to_plan":
            update["direct_escalated_to_planned"] = True
        return update

    async def replan(state: ResearchState):
        if not runtime.budget.can_replan(state):
            return {"stop_reason": "replan_budget_exhausted", "status": "assessing"}
        return {
            "replan_count": state.get("replan_count", 0) + 1,
            "status": "replanning",
            "updated_at": datetime.now(UTC),
        }

    async def mark_remaining_steps_skipped(state: ResearchState):
        plan = state.get("plan")
        if plan is None:
            return {}
        current = state.get("current_step_index", 0)
        runtimes = list(state.get("step_runtime", []))
        history = [item for item in runtimes if item.plan_version != plan.plan_version]
        by_id = {
            item.step_id: item for item in runtimes if item.plan_version == plan.plan_version
        }
        for step in plan.steps[current:]:
            by_id[step.step_id] = PlanStepRuntime(
                step_id=step.step_id,
                plan_version=plan.plan_version,
                status="skipped",
                skip_reason="evidence_sufficient",
                finished_at=datetime.now(UTC),
            )
        return {"step_runtime": [*history, *[by_id[step.step_id] for step in plan.steps]]}

    async def build_context(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        observations = [item for item in state.get("observations", []) if item.status == "success"]
        context = runtime.context_service.build(
            run_id=state["run_id"],
            repo_id=state["repo_id"],
            index_version_id=state["index_version_id"],
            query=state["query"],
            chunk_ids=_unique(item for obs in observations for item in obs.chunk_ids),
            entity_ids=_unique(item for obs in observations for item in obs.entity_ids),
            edge_notes=[obs.summary for obs in observations if obs.edge_ids and obs.summary],
            max_entities=runtime.budget.limits.max_final_context_items,
        )
        return {"context": context, "status": "building_context", "updated_at": datetime.now(UTC)}

    async def generate_answer(state: ResearchState):
        if runtime.cancelled(state):
            return _cancel_update()
        context = state.get("context")
        if context is None:
            return _failure("context_missing", "Context was not built.")
        if not state.get("answer_enabled", True):
            return {
                "answer": AgentResearchAnswer(
                    answer="", confidence=state.get("confidence", 0.0), evidence_only=True
                ),
                "status": "generating",
            }
        draft = await asyncio.to_thread(
            runtime.answer_generator.generate,
            state["query"], context,
            external_text_consent=state.get("external_text_consent", False),
        )
        return {
            "draft_answer": draft,
            "status": "generating",
            "updated_at": datetime.now(UTC),
        }

    async def validate_citations(state: ResearchState):
        if not state.get("answer_enabled", True):
            return {"status": "validating"}
        outcome = runtime.citation_validator.validate(state["draft_answer"], state["context"])
        errors = list(state.get("errors", []))
        if outcome.invalid_citation_ids:
            errors.append(AgentError(
                error_code="invalid_citations_removed",
                component="citation_validator",
                message="Generated citations not present in ContextBundle were removed.",
                context={"citation_ids": outcome.invalid_citation_ids},
            ))
        return {"draft_answer": outcome.answer, "errors": errors, "status": "validating"}

    async def verify_claims(state: ResearchState):
        if not state.get("answer_enabled", True):
            return {"status": "verifying"}
        return {
            "validated_answer": runtime.claim_verifier.verify(state["draft_answer"]),
            "status": "verifying",
        }

    async def finalize_answer(state: ResearchState):
        answer = state.get("answer")
        if state.get("answer_enabled", True):
            answer = runtime.finalizer.finalize(state["validated_answer"])
        terminal = "completed" if state.get("evidence_sufficient") else "partial"
        if answer and answer.evidence_only and state.get("answer_enabled", True):
            terminal = "partial"
        return {
            "answer": answer,
            "confidence": answer.confidence if answer else state.get("evidence_assessment").confidence,
            "status": terminal,
            "stop_reason": "completed" if terminal == "completed" else "insufficient_evidence",
            "updated_at": datetime.now(UTC),
        }

    async def finish_partial(state: ResearchState):
        observations = [item for item in state.get("observations", []) if item.status == "success"]
        context = state.get("context")
        if context is None:
            context = runtime.context_service.build(
                run_id=state["run_id"], repo_id=state["repo_id"],
                index_version_id=state["index_version_id"], query=state["query"],
                chunk_ids=_unique(item for obs in observations for item in obs.chunk_ids),
                entity_ids=_unique(item for obs in observations for item in obs.entity_ids),
                edge_notes=[obs.summary for obs in observations if obs.edge_ids and obs.summary],
                max_entities=runtime.budget.limits.max_final_context_items,
            )
        answer = AgentResearchAnswer(
            answer="现有证据不足，研究运行已在预算边界内结束。",
            confidence=state.get("evidence_assessment").confidence if state.get("evidence_assessment") else 0.0,
            evidence_only=True,
        )
        draft = None
        validated = None
        if state.get("answer_enabled", True) and context.items:
            draft = await asyncio.to_thread(
                runtime.answer_generator.generate,
                state["query"], context,
                external_text_consent=state.get("external_text_consent", False),
            )
            draft = runtime.citation_validator.validate(draft, context).answer
            validated = runtime.claim_verifier.verify(draft)
            answer = runtime.finalizer.finalize(validated)
        return {
            "context": context,
            "draft_answer": draft,
            "validated_answer": validated,
            "answer": answer,
            "status": "partial",
            "stop_reason": state.get("stop_reason") or "insufficient_evidence",
            "updated_at": datetime.now(UTC),
        }

    nodes = {
        "route_query": route_query,
        "direct_retrieve": direct_retrieve,
        "create_plan": create_plan,
        "validate_plan": validate_plan,
        "resolve_step_arguments": resolve_step_arguments,
        "mark_step_running": mark_step_running,
        "execute_step": execute_step,
        "assess_evidence": assess_evidence,
        "replan": replan,
        "mark_remaining_steps_skipped": mark_remaining_steps_skipped,
        "build_context": build_context,
        "generate_answer": generate_answer,
        "validate_citations": validate_citations,
        "verify_claims": verify_claims,
        "finalize_answer": finalize_answer,
        "finish_partial": finish_partial,
    }
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "route_query")
    graph.add_conditional_edges("route_query", _route_after_router, {
        "direct": "direct_retrieve", "planned": "create_plan", "end": END,
    })
    graph.add_edge("direct_retrieve", "assess_evidence")
    graph.add_edge("create_plan", "validate_plan")
    graph.add_conditional_edges("validate_plan", _route_after_validation, {
        "resolve": "resolve_step_arguments", "partial": "finish_partial", "end": END,
    })
    graph.add_conditional_edges("resolve_step_arguments", _route_after_resolution, {
        "execute": "mark_step_running", "assess": "assess_evidence", "end": END,
    })
    graph.add_edge("mark_step_running", "execute_step")
    graph.add_edge("execute_step", "assess_evidence")
    graph.add_conditional_edges("assess_evidence", _route_after_assessment, {
        "skip": "mark_remaining_steps_skipped",
        "next": "resolve_step_arguments",
        "plan": "create_plan",
        "replan": "replan",
        "partial": "finish_partial",
        "end": END,
    })
    graph.add_edge("replan", "create_plan")
    graph.add_edge("mark_remaining_steps_skipped", "build_context")
    graph.add_edge("build_context", "generate_answer")
    graph.add_edge("generate_answer", "validate_citations")
    graph.add_edge("validate_citations", "verify_claims")
    graph.add_edge("verify_claims", "finalize_answer")
    graph.add_edge("finalize_answer", END)
    graph.add_edge("finish_partial", END)
    return graph.compile(checkpointer=checkpointer)


async def _execute_step(
    runtime: ResearchGraphRuntime,
    state: ResearchState,
    step: PlanStep,
    plan_version: str,
    *,
    resolved=None,
) -> dict:
    resolved = resolved or runtime.executor.resolve(
        step=step,
        plan_version=plan_version,
        observations=state.get("observations", []),
    )
    outcome = await runtime.executor.execute(
        run_id=state["run_id"],
        repo_id=state["repo_id"],
        index_version_id=state["index_version_id"],
        plan_version=plan_version,
        step=step,
        resolved=resolved,
        observations=state.get("observations", []),
        state=state,
        cancel_check=lambda: runtime.cancelled(state),
    )
    return {
        "observations": [*state.get("observations", []), outcome.observation],
        "step_runtime": _replace_runtime(state, outcome.runtime),
        "current_step_index": state.get("current_step_index", 0) + 1 if plan_version != "direct" else 0,
        "tool_call_count": state.get("tool_call_count", 0) + outcome.actual_tool_calls,
        "tool_reuse_count": state.get("tool_reuse_count", 0) + outcome.reused_tool_calls,
        "tool_failure_count": state.get("tool_failure_count", 0) + outcome.tool_failures,
        "resolved_arguments": resolved.model.model_dump(mode="json"),
        "step_resolution_failed": False,
        "updated_at": datetime.now(UTC),
    }


def _route_after_router(state: ResearchState) -> str:
    if state.get("status") in {"cancelled", "failed"}:
        return "end"
    return state["route"]


def _route_after_validation(state: ResearchState) -> str:
    if state.get("status") == "cancelled":
        return "end"
    if state.get("status") == "failed":
        return "partial"
    return "resolve"


def _route_after_resolution(state: ResearchState) -> str:
    if state.get("status") == "cancelled":
        return "end"
    if state.get("status") == "failed" or state.get("step_resolution_failed"):
        return "assess"
    return "execute"


def _route_after_assessment(state: ResearchState) -> str:
    if state.get("status") in {"cancelled", "failed"}:
        return "end" if state.get("status") == "cancelled" else "partial"
    action = state["evidence_assessment"].next_action
    return {
        "build_context": "skip",
        "resolve_next": "next",
        "escalate_to_plan": "plan",
        "replan": "replan",
        "partial": "partial",
    }[action]


def _current_step(state: ResearchState) -> tuple[ResearchPlan | None, PlanStep | None]:
    plan = state.get("plan")
    index = state.get("current_step_index", 0)
    if plan is None or index >= len(plan.steps):
        return plan, None
    return plan, plan.steps[index]


def _replace_runtime(state: ResearchState, runtime: PlanStepRuntime) -> list[PlanStepRuntime]:
    values = list(state.get("step_runtime", []))
    for index, item in enumerate(values):
        if item.step_id == runtime.step_id and item.plan_version == runtime.plan_version:
            values[index] = runtime
            return values
    values.append(runtime)
    return values


def _failed_step_update(
    state: ResearchState,
    step: PlanStep,
    plan_version: str,
    error_code: str,
    message: str,
) -> dict:
    runtime = PlanStepRuntime(
        step_id=step.step_id,
        plan_version=plan_version,
        status="failed",
        error_code=error_code,
        finished_at=datetime.now(UTC),
    )
    return {
        "step_runtime": _replace_runtime(state, runtime),
        "current_step_index": state.get("current_step_index", 0) + 1,
        "tool_failure_count": state.get("tool_failure_count", 0) + 1,
        "errors": [*state.get("errors", []), AgentError(error_code=error_code, message=message)],
        "step_resolution_failed": True,
        "status": "executing",
    }


def _failure(error_code: str, message: str) -> dict:
    return {
        "status": "failed",
        "stop_reason": error_code,
        "errors": [AgentError(error_code=error_code, message=message)],
        "updated_at": datetime.now(UTC),
    }


def _cancel_update() -> dict:
    return {
        "cancel_requested": True,
        "status": "cancelled",
        "stop_reason": "cancel_requested",
        "updated_at": datetime.now(UTC),
    }


def _current_runtime_failed(state: ResearchState) -> bool:
    plan, step = _current_step(state)
    if step is None:
        return False
    return any(
        item.step_id == step.step_id and item.plan_version == plan.plan_version and item.status == "failed"
        for item in state.get("step_runtime", [])
    )


def _digest(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def _unique(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _as_datetime(value, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return default
