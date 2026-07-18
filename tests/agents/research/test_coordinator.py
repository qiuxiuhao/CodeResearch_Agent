from __future__ import annotations

import asyncio

from backend.app.agents.research.schemas import ResearchRunCreateRequest
from backend.app.agents.research.state import ResearchState
from backend.app.persistence.research_checkpoint import ResearchCheckpointRuntime
from backend.app.persistence.research_run_store import ResearchRunStore
from backend.app.services.research_run_coordinator import ResearchRunCoordinator


def test_coordinator_claims_and_completes_run_once(tmp_path) -> None:
    asyncio.run(_exercise_coordinator(tmp_path))


async def _exercise_coordinator(tmp_path) -> None:
    calls = 0

    def graph_factory(saver):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(ResearchState)

        async def complete(_state):
            nonlocal calls
            calls += 1
            return {"status": "completed", "stop_reason": "completed"}

        graph.add_node("complete", complete)
        graph.add_edge(START, "complete")
        graph.add_edge("complete", END)
        return graph.compile(checkpointer=saver)

    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    checkpoint = ResearchCheckpointRuntime(tmp_path / "checkpoint.sqlite3")
    coordinator = ResearchRunCoordinator(
        run_store=store, checkpoint_runtime=checkpoint, graph_factory=graph_factory,
        poll_seconds=0.02, lease_seconds=5, max_concurrent_runs=1,
    )
    await coordinator.start()
    try:
        run, _ = store.create_run(
            repo_id="repo", index_version_id="v1",
            request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
        )
        for _ in range(100):
            current = store.get_run(run["run_id"])
            if current["status"] == "completed":
                break
            await asyncio.sleep(0.02)
        assert store.get_run(run["run_id"])["status"] == "completed"
        assert calls == 1
    finally:
        await coordinator.stop()


def test_graceful_shutdown_leaves_run_resumable(tmp_path) -> None:
    asyncio.run(_exercise_shutdown(tmp_path))


async def _exercise_shutdown(tmp_path) -> None:
    entered = asyncio.Event()

    def graph_factory(saver):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(ResearchState)

        async def block(_state):
            entered.set()
            await asyncio.Event().wait()
            return {"status": "completed"}

        graph.add_node("block", block)
        graph.add_edge(START, "block")
        graph.add_edge("block", END)
        return graph.compile(checkpointer=saver)

    store = ResearchRunStore(tmp_path / "shutdown-runs.sqlite3")
    coordinator = ResearchRunCoordinator(
        run_store=store,
        checkpoint_runtime=ResearchCheckpointRuntime(tmp_path / "shutdown-checkpoint.sqlite3"),
        graph_factory=graph_factory, poll_seconds=0.01, lease_seconds=5, max_concurrent_runs=1,
    )
    await coordinator.start()
    run, _ = store.create_run(
        repo_id="repo", index_version_id="v1",
        request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    await coordinator.stop(grace_seconds=0.01)
    assert store.get_run(run["run_id"])["status"] == "interrupted"
