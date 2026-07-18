from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from backend.app.agents.research.graph import ResearchGraphRuntime, build_research_agent_graph, initial_research_state
from backend.app.agents.research.tool_registry import (
    GetGraphNeighborsInput,
    SearchHybridInput,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from backend.app.retrieval.schemas import ContextBundle, ContextItem, RetrievalEvidence
from backend.app.persistence.research_checkpoint import ResearchCheckpointRuntime


class _ContextService:
    def build(self, **kwargs):
        evidence = RetrievalEvidence(
            evidence_id="ev", source_type="code", path="model.py", start_line=1, end_line=3
        )
        return ContextBundle(
            repo_id=kwargs["repo_id"], index_version_id=kwargs["index_version_id"],
            query_id=kwargs["run_id"],
            items=[ContextItem(
                context_id="ctx", entity_id="ent", chunk_ids=["chunk"], title="model.forward",
                text="def forward(): pass", token_count=5, truncated=False, rank=1,
                evidence=[evidence],
            )],
            estimated_tokens=5, token_count_method="conservative_code_estimate", token_budget=6000,
        )


def _initial(query_type: str):
    now = datetime.now(UTC).isoformat()
    return initial_research_state(
        run={
            "run_id": "run", "thread_id": "run", "repo_id": "repo",
            "index_version_id": "v1", "resume_count": 0, "created_at": now,
        },
        request={"query": "explain", "query_type": query_type, "answer_enabled": True},
    )


def test_direct_route_stops_when_evidence_is_sufficient() -> None:
    async def search(_input, _context):
        return ToolResult(entity_ids=["ent"], chunk_ids=["chunk"], evidence_ids=["ev"])

    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, search, 1, 30))
    graph = build_research_agent_graph(ResearchGraphRuntime(registry, _ContextService()))
    state = asyncio.run(graph.ainvoke(_initial("symbol_lookup")))
    assert state["status"] == "completed"
    assert state["route"] == "direct"
    assert state["tool_call_count"] == 1
    assert state["answer"].citations[0].evidence_id == "ev"


def test_direct_to_planned_escalation_does_not_increment_replan() -> None:
    calls = 0

    async def search(_input, _context):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ToolResult()
        return ToolResult(entity_ids=["ent"], chunk_ids=["chunk"], evidence_ids=["ev"])

    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, search, 1, 30))
    graph = build_research_agent_graph(ResearchGraphRuntime(registry, _ContextService()))
    state = asyncio.run(graph.ainvoke(_initial("symbol_lookup")))
    assert state["status"] == "completed"
    assert state["direct_escalated_to_planned"] is True
    assert state["replan_count"] == 0
    assert state["tool_call_count"] == 2


def test_planned_route_executes_graph_after_preliminary_search() -> None:
    async def search(_input, _context):
        return ToolResult(entity_ids=["ent"], chunk_ids=["chunk"], evidence_ids=["ev"])

    async def graph(_input, _context):
        return ToolResult(entity_ids=["ent", "ent2"], edge_ids=["edge"], evidence_ids=["ev"])

    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, search, 1, 30))
    registry.register(ToolSpec("get_graph_neighbors", GetGraphNeighborsInput, graph, 1, 30))
    compiled = build_research_agent_graph(ResearchGraphRuntime(registry, _ContextService()))
    state = asyncio.run(compiled.ainvoke(_initial("architecture")))
    assert state["status"] == "completed"
    tools = [item.tool_name for item in state["observations"]]
    assert tools == ["search_hybrid", "get_graph_neighbors"], {
        "tools": tools,
        "assessment": state.get("evidence_assessment"),
        "runtime": state.get("step_runtime"),
        "errors": state.get("errors"),
        "index": state.get("current_step_index"),
        "replans": state.get("replan_count"),
    }
    assert state["replan_count"] == 0


def test_graph_state_round_trips_through_strict_sqlite_checkpoint(tmp_path) -> None:
    asyncio.run(_checkpointed_graph(tmp_path))


async def _checkpointed_graph(tmp_path) -> None:
    async def search(_input, _context):
        return ToolResult(entity_ids=["ent"], chunk_ids=["chunk"], evidence_ids=["ev"])

    registry = ToolRegistry()
    registry.register(ToolSpec("search_hybrid", SearchHybridInput, search, 1, 30))
    checkpoint = ResearchCheckpointRuntime(tmp_path / "checkpoint.sqlite3")
    saver = await checkpoint.start()
    try:
        graph = build_research_agent_graph(
            ResearchGraphRuntime(registry, _ContextService()), checkpointer=saver
        )
        config = {"configurable": {"thread_id": "run"}}
        state = await graph.ainvoke(_initial("symbol_lookup"), config=config)
        assert state["status"] == "completed"
        saved = await graph.aget_state(config)
        assert saved.values["answer"].citations[0].evidence_id == "ev"
    finally:
        await checkpoint.close()
