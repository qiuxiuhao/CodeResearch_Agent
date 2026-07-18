from __future__ import annotations

import asyncio

from backend.app.agents.research.executor import ResearchExecutor
from backend.app.agents.research.schemas import PlanStep
from backend.app.agents.research.tool_registry import SearchHybridInput, ToolRegistry, ToolResult, ToolSpec


def test_replan_reuses_identical_successful_tool_call() -> None:
    asyncio.run(_exercise_reuse())


async def _exercise_reuse() -> None:
    calls = 0

    async def handler(_input, _context):
        nonlocal calls
        calls += 1
        return ToolResult(entity_ids=["ent"], chunk_ids=["chunk"], evidence_ids=["ev"])

    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, handler, 1, 30))
    executor = ResearchExecutor(registry)
    step = PlanStep(
        step_id="search", ordinal=0, goal="search", tool_name="search_hybrid",
        literal_arguments={"query": "x"}, success_criteria=["result"],
    )
    resolved = executor.resolve(step=step, plan_version="1", observations=[])
    first = await executor.execute(
        run_id="run", repo_id="repo", index_version_id="v1", plan_version="1",
        step=step, resolved=resolved, observations=[], state={},
    )
    second = await executor.execute(
        run_id="run", repo_id="repo", index_version_id="v1", plan_version="2",
        step=step, resolved=resolved, observations=[first.observation], state={"tool_call_count": 1},
    )
    assert calls == 1
    assert second.observation.reused is True
    assert second.actual_tool_calls == 0
    assert second.reused_tool_calls == 1
