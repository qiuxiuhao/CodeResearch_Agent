from __future__ import annotations

import pytest

from backend.app.agents.research.argument_resolver import StepArgumentResolver
from backend.app.agents.research.plan_validator import PlanValidationError, PlanValidator
from backend.app.agents.research.schemas import (
    ArgumentBinding,
    PlanStep,
    ResearchPlan,
    StepOutputRef,
    ToolObservation,
)
from backend.app.agents.research.tool_registry import ToolRegistry, ToolSpec, ToolResult, SearchHybridInput, GetGraphNeighborsInput


async def _empty(_tool_input, _context):
    return ToolResult()


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, _empty, 1, 30))
    registry.register(ToolSpec("get_graph_neighbors", GetGraphNeighborsInput, _empty, 1, 30))
    return registry


def _observation(plan_version: str = "1") -> ToolObservation:
    return ToolObservation(
        observation_id="obs-1", step_id="search", plan_version=plan_version,
        tool_name="search_hybrid", resolved_arguments_hash="hash", tool_call_key="key",
        step_execution_id="exec", status="success", entity_ids=["ent-a", "ent-b"],
    )


def test_step_argument_resolves_previous_entity_id() -> None:
    step = PlanStep(
        step_id="graph", ordinal=1, goal="graph", tool_name="get_graph_neighbors",
        literal_arguments={"edge_types": ["CALLS"]}, dependencies=["search"],
        argument_bindings=[ArgumentBinding(
            argument_name="entity_ids",
            from_step=StepOutputRef(step_id="search", field="entity_ids", selection="unique"),
        )],
        success_criteria=["edge"],
    )
    resolved = StepArgumentResolver(_registry()).resolve(step, [_observation()], plan_version="1")
    assert resolved.model.entity_ids == ["ent-a", "ent-b"]


def test_step_reference_cannot_target_future_step() -> None:
    search = PlanStep(
        step_id="search", ordinal=0, goal="search", tool_name="search_hybrid",
        literal_arguments={"query": "x"}, success_criteria=["result"],
    )
    graph = PlanStep(
        step_id="graph", ordinal=1, goal="graph", tool_name="get_graph_neighbors",
        literal_arguments={"edge_types": ["CALLS"]}, dependencies=["future"],
        argument_bindings=[ArgumentBinding(
            argument_name="entity_ids", from_step=StepOutputRef(step_id="future", field="entity_ids", selection="all")
        )], success_criteria=["result"],
    )
    future = search.model_copy(update={"step_id": "future", "ordinal": 2})
    plan = ResearchPlan(
        plan_id="p", plan_version="1", query_type="architecture", goal="x",
        steps=[search, graph, future], success_criteria=["done"],
    )
    with pytest.raises(PlanValidationError, match="not a prior step"):
        PlanValidator(_registry()).validate(plan)


def test_binding_ignores_observations_from_previous_plan_version() -> None:
    step = PlanStep(
        step_id="graph", ordinal=1, goal="graph", tool_name="get_graph_neighbors",
        literal_arguments={"edge_types": ["CALLS"]}, dependencies=["search"],
        argument_bindings=[ArgumentBinding(
            argument_name="entity_ids",
            from_step=StepOutputRef(step_id="search", field="entity_ids", selection="all"),
        )], success_criteria=["result"],
    )
    with pytest.raises(ValueError, match="Required output"):
        StepArgumentResolver(_registry()).resolve(step, [_observation("1")], plan_version="2")
