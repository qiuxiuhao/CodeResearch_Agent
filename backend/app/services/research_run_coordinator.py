from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from backend.app.agents.research.budget import AgentBudget
from backend.app.agents.research.graph import initial_research_state
from backend.app.agents.research.graph import GRAPH_VERSION, STATE_SCHEMA_VERSION
from backend.app.agents.research.schemas import TERMINAL_STATUSES
from backend.app.persistence.research_checkpoint import ResearchCheckpointRuntime
from backend.app.persistence.research_run_store import ResearchRunStore, ResearchRunStoreError, RunLease


ACTIVE_STATUSES = {
    "queued", "routing", "planning", "retrieving", "executing", "assessing", "replanning",
    "building_context", "generating", "validating", "verifying", "finalizing", "interrupted",
}


class ResearchRunCoordinator:
    def __init__(
        self,
        *,
        run_store: ResearchRunStore,
        checkpoint_runtime: ResearchCheckpointRuntime,
        graph_factory: Callable[[object], object],
        poll_seconds: float = 0.5,
        lease_seconds: float = 30.0,
        max_concurrent_runs: int = 2,
    ) -> None:
        self.run_store = run_store
        self.checkpoint_runtime = checkpoint_runtime
        self.graph_factory = graph_factory
        self.poll_seconds = max(0.05, poll_seconds)
        self.lease_seconds = max(5.0, lease_seconds)
        self.max_concurrent_runs = max(1, max_concurrent_runs)
        self.owner = f"coordinator-{os.getpid()}-{uuid4().hex}"
        self._graph = None
        self._loop_task: asyncio.Task | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self.run_store.migrate()
        saver = await self.checkpoint_runtime.start()
        self._graph = self.graph_factory(saver)
        self._stopping.clear()
        self._loop_task = asyncio.create_task(self._run_loop(), name="research-run-coordinator")

    async def stop(self, *, grace_seconds: float = 5.0) -> None:
        self._stopping.set()
        if self._loop_task:
            self._loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._loop_task
        active = list(self._tasks.items())
        if active:
            done, pending = await asyncio.wait(
                [task for _, task in active], timeout=max(0.0, grace_seconds)
            )
            for task in pending:
                task.cancel()
            for run_id, task in active:
                if task in pending:
                    with suppress(Exception):
                        current = self.run_store.get_run(run_id)
                        if current["status"] not in TERMINAL_STATUSES:
                            self.run_store.update_status(
                                run_id, "interrupted", allowed_from=[current["status"]],
                                stop_reason="application_shutdown", retryable=True,
                            )
        await self.checkpoint_runtime.close()

    def notify(self) -> None:
        # The bounded polling loop is the durable wakeup mechanism. This method exists so API
        # callers need not create an unmanaged background task.
        return None

    async def purge_terminal_runs_before(self, cutoff: datetime, *, limit: int = 100) -> int:
        removed = 0
        for run in self.run_store.terminal_runs_before(cutoff, limit=limit):
            await self.checkpoint_runtime.delete_thread(run["thread_id"])
            removed += self.run_store.delete_terminal_run(run["run_id"])
        return removed

    async def resume(self, run_id: str) -> dict:
        run = self.run_store.get_run(run_id)
        if run["graph_version"] != GRAPH_VERSION or run["state_schema_version"] != STATE_SCHEMA_VERSION:
            raise ResearchRunStoreError(
                "run_version_incompatible", "The run graph/state version is not compatible with this service."
            )
        if not await self.checkpoint_runtime.checkpoint_exists(run["thread_id"]):
            raise ResearchRunStoreError(
                "checkpoint_unavailable", "The run has no checkpoint and cannot be resumed."
            )
        if run_id in self._tasks:
            return run
        lease = self.run_store.acquire_lease(run_id, self.owner, ttl_seconds=self.lease_seconds)
        if lease is None:
            return self.run_store.get_run(run_id)
        try:
            resumed = self.run_store.mark_resumed(run_id)
        except Exception:
            self.run_store.release_lease(lease)
            raise
        task = asyncio.create_task(self._execute_run(run_id, lease), name=f"research-run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task, key=run_id: self._tasks.pop(key, None))
        return resumed

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            for run_id in self.run_store.list_claimable(limit=self.max_concurrent_runs * 2):
                if len(self._tasks) >= self.max_concurrent_runs:
                    break
                if run_id in self._tasks:
                    continue
                lease = self.run_store.acquire_lease(run_id, self.owner, ttl_seconds=self.lease_seconds)
                if lease is None:
                    continue
                task = asyncio.create_task(self._execute_run(run_id, lease), name=f"research-run-{run_id}")
                self._tasks[run_id] = task
                task.add_done_callback(lambda _task, key=run_id: self._tasks.pop(key, None))
            await asyncio.sleep(self.poll_seconds)

    async def _execute_run(self, run_id: str, lease: RunLease) -> None:
        execution_task = asyncio.current_task()
        heartbeat = asyncio.create_task(self._heartbeat(lease), name=f"research-lease-{run_id}")
        heartbeat.add_done_callback(
            lambda task: execution_task.cancel()
            if execution_task and not task.cancelled() and task.exception() is not None
            else None
        )
        try:
            run = self.run_store.get_run(run_id)
            if run["status"] == "cancelling" or run["cancel_requested"]:
                self.run_store.update_status(run_id, "cancelled", allowed_from=[run["status"]])
                return
            config = {"configurable": {"thread_id": run["thread_id"]}}
            checkpoint_exists = await self.checkpoint_runtime.checkpoint_exists(run["thread_id"])
            if run["status"] in {"interrupted", "paused"}:
                if not checkpoint_exists:
                    raise ResearchRunStoreError(
                        "checkpoint_unavailable", "A resumable run has no checkpoint."
                    )
                graph_input = None
            elif checkpoint_exists:
                graph_input = None
            else:
                graph_input = initial_research_state(run=run, request=run["request"])

            final_state = None
            async for state in self._graph.astream(graph_input, config=config, stream_mode="values"):
                final_state = state
                await self._publish_state(run_id, state)
            if final_state is None:
                raise ResearchRunStoreError("checkpoint_unavailable", "The graph produced no state.")
            await self._publish_terminal(run_id, final_state)
        except asyncio.CancelledError:
            if not self._stopping.is_set() and heartbeat.done() and not heartbeat.cancelled():
                current = self.run_store.get_run(run_id)
                if current["status"] not in TERMINAL_STATUSES:
                    with suppress(ResearchRunStoreError):
                        self.run_store.update_status(
                            run_id, "interrupted", allowed_from=[current["status"]],
                            stop_reason="research_run_lease_lost", retryable=True,
                        )
            raise
        except Exception as exc:
            current = self.run_store.get_run(run_id)
            if current["status"] not in TERMINAL_STATUSES:
                with suppress(ResearchRunStoreError):
                    self.run_store.update_status(
                        run_id, "failed", allowed_from=[current["status"]],
                        stop_reason=getattr(exc, "error_code", "agent_run_failed"),
                        retryable=bool(getattr(exc, "retryable", False)),
                        errors=[{
                            "error_code": getattr(exc, "error_code", "agent_run_failed"),
                            "component": "research_coordinator", "message": str(exc),
                            "retryable": bool(getattr(exc, "retryable", False)),
                        }],
                    )
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, RuntimeError):
                await heartbeat
            self.run_store.release_lease(lease)

    async def _publish_state(self, run_id: str, state: dict) -> None:
        status = str(state.get("status", "executing"))
        if status in TERMINAL_STATUSES:
            return
        current = self.run_store.get_run(run_id)
        if current["status"] == "cancelling":
            return
        with suppress(ResearchRunStoreError):
            self.run_store.update_status(
                run_id, status, allowed_from=[current["status"]], route=state.get("route"),
                result=_result_view(state), budget=AgentBudget().snapshot(state).model_dump(mode="json"),
                errors=jsonable_encoder(state.get("errors", [])),
            )

    async def _publish_terminal(self, run_id: str, state: dict) -> None:
        current = self.run_store.get_run(run_id)
        target = state.get("status")
        if current["status"] == "cancelling" or state.get("cancel_requested"):
            target = "cancelled"
        if target not in TERMINAL_STATUSES:
            target = "partial"
        result = _result_view(state)
        budget = AgentBudget().snapshot(state).model_dump(mode="json")
        self.run_store.update_status(
            run_id, target, allowed_from=[current["status"]],
            route=state.get("route"), stop_reason=state.get("stop_reason"),
            result=result, budget=budget,
            errors=jsonable_encoder(state.get("errors", [])),
        )

    async def _heartbeat(self, lease: RunLease) -> None:
        current = lease
        while True:
            await asyncio.sleep(self.lease_seconds / 3)
            renewed = self.run_store.renew_lease(current, ttl_seconds=self.lease_seconds)
            if renewed is None:
                raise RuntimeError("research_run_lease_lost")
            current = renewed


def _result_view(state: dict) -> dict:
    return jsonable_encoder({
        "current_step": _current_runtime(state),
        "observations": state.get("observations", []),
        "evidence_ids": state.get("evidence_ids", []),
        "answer": state.get("answer"),
        "context": state.get("context"),
        "warnings": [
            item.message if hasattr(item, "message") else str(item.get("message", "agent_warning"))
            for item in state.get("errors", [])
        ],
    })


def _current_runtime(state: dict):
    runtimes = state.get("step_runtime", [])
    active = [item for item in runtimes if getattr(item, "status", None) in {"resolving", "running"}]
    return active[-1] if active else (runtimes[-1] if runtimes else None)
