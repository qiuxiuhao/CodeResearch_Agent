from __future__ import annotations

import hashlib

from backend.app.llm.prompt_registry import load_registered_prompt
from backend.app.llm.router import ModelRouter
from backend.app.schemas.llm_explanation import EvidenceItem

from backend.app.agents.research.schemas import (
    ArgumentBinding,
    ExpectedEvidence,
    PlanStep,
    ResearchPlan,
    StepOutputRef,
    StructuredPlanResponse,
)
from backend.app.retrieval.schemas import QueryType
from backend.app.agents.research.plan_validator import PlanValidator


class RuleBasedPlanner:
    """Deterministic fallback planner; model planners must return the same strict schema."""

    def create_plan(
        self, *, query: str, query_type: QueryType, plan_version: int = 1,
        external_text_consent: bool = False,
    ) -> ResearchPlan:
        steps = self._steps(query, query_type)
        digest = hashlib.sha256(
            f"{plan_version}\0{query_type}\0{query}".encode("utf-8")
        ).hexdigest()[:20]
        return ResearchPlan(
            plan_id=f"plan_{digest}",
            plan_version=str(plan_version),
            query_type=query_type,
            goal=query,
            steps=steps,
            success_criteria=["Collect the required repository evidence within the agent budget."],
            expected_evidence=_expected(query_type),
        )

    def _steps(self, query: str, query_type: QueryType) -> list[PlanStep]:
        search_tool = "search_paper" if query_type == "paper_alignment" else "search_hybrid"
        search_arguments = {"query": query}
        if search_tool == "search_hybrid":
            search_arguments["query_type"] = query_type
            search_arguments["top_k"] = 10
        first = PlanStep(
            step_id="step_search",
            ordinal=0,
            goal="Find initial evidence candidates.",
            tool_name=search_tool,
            literal_arguments=search_arguments,
            success_criteria=["At least one entity or chunk is returned."],
            expected_evidence=_expected(query_type),
        )
        if query_type == "call_chain":
            second = PlanStep(
                step_id="step_call_path",
                ordinal=1,
                goal="Resolve the call path between the first two candidate entities.",
                tool_name="get_call_path",
                literal_arguments={"max_hops": 2, "max_paths": 5},
                argument_bindings=[
                    ArgumentBinding(argument_name="source_entity_id", from_step=StepOutputRef(
                        step_id=first.step_id, field="entity_ids", index=0
                    )),
                    ArgumentBinding(argument_name="target_entity_id", from_step=StepOutputRef(
                        step_id=first.step_id, field="entity_ids", index=1
                    )),
                ],
                dependencies=[first.step_id],
                success_criteria=["A resolved path or an explicit unreachable result is returned."],
                expected_evidence=_expected(query_type),
            )
            return [first, second]
        if query_type in {"architecture", "training_process", "inference_process", "general_repository"}:
            second = PlanStep(
                step_id="step_graph",
                ordinal=1,
                goal="Inspect graph relations around the retrieved entities.",
                tool_name="get_graph_neighbors",
                literal_arguments={
                    "edge_types": ["CONTAINS", "DEFINES", "CALLS", "INSTANTIATES", "IMPORTS"],
                    "direction": "both",
                    "max_results": 30,
                },
                argument_bindings=[ArgumentBinding(
                    argument_name="entity_ids",
                    from_step=StepOutputRef(step_id=first.step_id, field="entity_ids", selection="unique"),
                )],
                dependencies=[first.step_id],
                success_criteria=["At least one relevant graph relation is returned."],
                expected_evidence=_expected(query_type),
            )
            return [first, second]
        if query_type == "paper_alignment":
            second = PlanStep(
                step_id="step_alignment",
                ordinal=1,
                goal="Read code-paper alignment edges for the leading paper entity.",
                tool_name="get_alignment",
                literal_arguments={"max_results": 20},
                argument_bindings=[ArgumentBinding(
                    argument_name="entity_id",
                    from_step=StepOutputRef(step_id=first.step_id, field="entity_ids"),
                )],
                dependencies=[first.step_id],
                success_criteria=["Paper and code evidence are linked by a real alignment edge."],
                expected_evidence=_expected(query_type),
            )
            return [first, second]
        return [first]


class StructuredPlanner:
    def __init__(
        self,
        router: ModelRouter,
        *,
        fallback: RuleBasedPlanner | None = None,
        validator: PlanValidator | None = None,
    ) -> None:
        self.router = router
        self.fallback = fallback or RuleBasedPlanner()
        self.validator = validator

    def create_plan(
        self, *, query: str, query_type: QueryType, plan_version: int = 1,
        external_text_consent: bool = False,
    ) -> ResearchPlan:
        if not external_text_consent or not self.router.has_available_provider:
            return self.fallback.create_plan(
                query=query, query_type=query_type, plan_version=plan_version
            )
        result = self.router.generate_structured(
            task_type="research_plan",
            context_id=f"plan:{hashlib.sha256(query.encode('utf-8')).hexdigest()[:16]}",
            system_prompt=load_registered_prompt("research_plan"),
            input_payload={
                "query": query,
                "query_type": query_type,
                "plan_version": str(plan_version),
                "allowed_tools": [
                    "search_hybrid", "get_symbol_source", "get_graph_neighbors", "get_call_path",
                    "get_model_flow", "search_paper", "get_alignment", "inspect_config",
                ],
                "budgets": {"max_plan_steps": 6, "max_tool_calls": 10, "max_graph_hops": 2},
            },
            response_model=StructuredPlanResponse,
            evidence_catalog=[],
            prompt_version="1.0",
            result_validator=lambda value: _validate_planner_identity(
                value, query_type=query_type, plan_version=plan_version
            ),
        )
        if result.value is None:
            return self.fallback.create_plan(
                query=query, query_type=query_type, plan_version=plan_version
            )
        plan = StructuredPlanResponse.model_validate(result.value).plan
        if self.validator is not None:
            try:
                return self.validator.validate(plan)
            except ValueError:
                return self.fallback.create_plan(
                    query=query, query_type=query_type, plan_version=plan_version
                )
        return plan


def _validate_planner_identity(value, *, query_type: QueryType, plan_version: int) -> None:
    response = StructuredPlanResponse.model_validate(value)
    if response.plan.query_type != query_type:
        raise ValueError("Planner changed the validated query type.")
    if response.plan.plan_version != str(plan_version):
        raise ValueError("Planner changed the server-controlled plan version.")


def _expected(query_type: QueryType) -> list[ExpectedEvidence]:
    if query_type == "paper_alignment":
        return [
            ExpectedEvidence(evidence_type="paper", description="Paper page or figure evidence"),
            ExpectedEvidence(evidence_type="code", description="Code path and line evidence"),
            ExpectedEvidence(evidence_type="alignment", description="ALIGNS_WITH edge evidence"),
        ]
    if query_type in {"call_chain", "architecture", "training_process", "inference_process"}:
        return [
            ExpectedEvidence(evidence_type="code", description="Code entity evidence"),
            ExpectedEvidence(evidence_type="graph", description="Resolved graph edge evidence"),
        ]
    return [ExpectedEvidence(evidence_type="code", description="Code path and line evidence")]
