from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.evaluation.evaluation_service import EvaluationService
from backend.app.evaluation.graph import EvaluationGraph
from backend.app.evaluation.store_protocol import EvaluationStoreError
from backend.app.persistence.evaluation_store import EvaluationLease, EvaluationStore
from backend.app.observability.context import start_span_or_root
from backend.app.services.observability_runtime import get_observability_runtime


class EvaluationRunCoordinator:
    """Runs evaluation jobs with a bounded worker set and a recoverable SQLite lease."""

    def __init__(
        self,
        *,
        store: EvaluationStore,
        service: EvaluationService,
        max_concurrent_runs: int = 1,
        poll_seconds: float = 0.25,
        lease_seconds: int = 60,
    ) -> None:
        self.store = store
        self.service = service
        self.graph = EvaluationGraph(service)
        self.max_concurrent_runs = max(1, max_concurrent_runs)
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.owner = f"evaluation-coordinator-{uuid4().hex}"
        self._stop = asyncio.Event()
        self._notify = asyncio.Event()
        self._manager: asyncio.Task | None = None
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self.store.migrate()
        if self._manager is None:
            self._manager = asyncio.create_task(self._run_manager(), name="evaluation-run-manager")

    async def stop(self, grace_seconds: float = 5.0) -> None:
        self._stop.set()
        self._notify.set()
        if self._manager is not None:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._manager, grace_seconds)
        if self._tasks:
            done, pending = await asyncio.wait(self._tasks.values(), timeout=grace_seconds)
            for task in pending:
                task.cancel()
            for task in done:
                with suppress(Exception):
                    task.result()
        self._manager = None
        self._tasks.clear()

    def notify(self) -> None:
        self._notify.set()

    async def _run_manager(self) -> None:
        while not self._stop.is_set():
            self._reap()
            capacity = self.max_concurrent_runs - len(self._tasks)
            if capacity > 0:
                for run in self.store.list_claimable_runs(capacity):
                    lease = self.store.acquire_lease(
                        run.run_id, self.owner, lease_seconds=self.lease_seconds
                    )
                    if lease is None:
                        continue
                    self._tasks[run.run_id] = asyncio.create_task(
                        self._execute(lease), name=f"evaluation-{run.run_id}"
                    )
            self._notify.clear()
            try:
                await asyncio.wait_for(self._notify.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
        self._reap()

    async def _execute(self, lease: EvaluationLease) -> None:
        run = self.store.get_run(lease.run_id)
        runtime = get_observability_runtime()
        handle = start_span_or_root(
            operation="evaluation.run",
            trace_type="evaluation",
            component="evaluation",
            force_root=True,
            run_id=run.run_id,
            attributes={
                "cra.run.id": run.run_id,
                "cra.dataset.version": run.dataset_version_id,
                "cra.subject.id": run.subject_id,
                "cra.evaluation.mode": run.mode,
                "cra.evaluation.case_count": int(run.case_counts.get("total", 0)),
            },
        )
        async with handle:
            queued_from = runtime.consume_enqueue_link(run.run_id)
            if queued_from:
                handle.link(
                    queued_from[0], linked_span_id=queued_from[1], relation=queued_from[2]
                )
            handle.artifact("run", run.run_id, role="evaluation_run")
            await self._execute_impl(lease, handle)

    async def _execute_impl(self, lease: EvaluationLease, trace_handle) -> None:
        finished = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(lease, finished), name=f"evaluation-heartbeat-{lease.run_id}"
        )
        try:
            await self.graph.invoke(lease.run_id)
        except Exception as exc:
            self._mark_failed_if_needed(lease.run_id, exc)
        finally:
            finished.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            self.store.release_lease(lease)
            final = self.store.get_run(lease.run_id)
            trace_handle.event(
                "evaluation.terminal",
                attributes={
                    "cra.status": final.status,
                    "cra.count": int(final.case_counts.get("completed", 0)),
                },
            )
            if final.status in {"failed", "cancelled", "partial"}:
                trace_handle.end(
                    status="error" if final.status == "failed" else (
                        "cancelled" if final.status == "cancelled" else "ok"
                    ),
                    completion_status=final.status,
                )

    async def _heartbeat(self, lease: EvaluationLease, finished: asyncio.Event) -> None:
        current = lease
        interval = max(1.0, self.lease_seconds / 3)
        while not finished.is_set():
            try:
                await asyncio.wait_for(finished.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                current = await asyncio.to_thread(
                    self.store.renew_lease, current, lease_seconds=self.lease_seconds
                )

    def _mark_failed_if_needed(self, run_id: str, exc: Exception) -> None:
        run = self.store.get_run(run_id)
        if run.status in {"completed", "partial", "failed", "cancelled"}:
            return
        now = datetime.now(UTC)
        failed = run.model_copy(
            update={
                "status": "failed",
                "complete": False,
                "error_code": getattr(exc, "error_code", "evaluation_run_failed"),
                "incomplete_reason_codes": ["execution_failure"],
                "updated_at": now,
                "finished_at": now,
            }
        )
        self.store.update_run(failed)

    def _reap(self) -> None:
        for run_id, task in list(self._tasks.items()):
            if task.done():
                with suppress(Exception):
                    task.result()
                self._tasks.pop(run_id, None)
