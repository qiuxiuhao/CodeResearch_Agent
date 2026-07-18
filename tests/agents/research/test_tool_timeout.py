from __future__ import annotations

import asyncio

from backend.app.agents.research.tool_registry import (
    SearchHybridInput,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


def test_late_tool_result_is_discarded() -> None:
    asyncio.run(_timeout())


async def _timeout() -> None:
    returned = False

    async def slow(_input, _context):
        nonlocal returned
        try:
            await asyncio.sleep(0.1)
        finally:
            returned = True
        return ToolResult(entity_ids=["late"])

    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, slow, 0.01, 30))
    result = await registry.invoke(
        "search_hybrid", SearchHybridInput(query="x"),
        ToolExecutionContext(run_id="run", repo_id="repo", index_version_id="v1"),
    )
    assert result.status == "timeout"
    assert result.result.entity_ids == []
    assert returned is True
