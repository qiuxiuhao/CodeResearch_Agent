from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import uuid4

from backend.app.alignment.alignment_service import AlignmentService
from backend.app.persistence.alignment_store import AlignmentLease, AlignmentStore, AlignmentStoreError


class AlignmentRunCoordinator:
    def __init__(
        self,
        *,
        store: AlignmentStore,
        service: AlignmentService,
        max_concurrent_runs: int = 2,
        poll_seconds: float = 0.25,
        lease_seconds: int = 60,
    ) -> None:
        self.store = store
        self.service = service
        self.max_concurrent_runs = max(1, max_concurrent_runs)
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.owner = f"alignment-coordinator-{uuid4().hex}"
        self._stop = asyncio.Event()
        self._notify = asyncio.Event()
        self._manager: asyncio.Task | None = None
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self.store.migrate()
        if self._manager is None:
            self._manager = asyncio.create_task(self._run_manager(), name="alignment-run-manager")

    async def stop(self, grace_seconds: float = 5.0) -> None:
        self._stop.set()
        self._notify.set()
        if self._manager:
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
                    lease = self.store.acquire_lease(run["run_id"], self.owner, lease_seconds=self.lease_seconds)
                    if lease is None:
                        continue
                    task = asyncio.create_task(self._execute(lease), name=f"alignment-{run['run_id']}")
                    self._tasks[run["run_id"]] = task
            self._notify.clear()
            try:
                await asyncio.wait_for(self._notify.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
        self._reap()

    async def _execute(self, lease: AlignmentLease) -> None:
        finished = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(lease, finished), name=f"alignment-heartbeat-{lease.run_id}"
        )
        try:
            await asyncio.to_thread(self.service.process_run, lease.run_id, lease)
        except AlignmentStoreError as exc:
            if exc.error_code not in {"alignment_cancelled", "alignment_lease_lost"}:
                self._mark_failed_if_needed(lease.run_id, exc)
        except Exception as exc:
            self._mark_failed_if_needed(lease.run_id, exc)
        finally:
            finished.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            self.store.release_lease(lease)

    async def _heartbeat(self, lease: AlignmentLease, finished: asyncio.Event) -> None:
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
        if run["status"] in {"active", "failed", "cancelled", "superseded"}:
            return
        self.store.update_status(
            run_id,
            "failed",
            allowed_from=[run["status"]],
            error_code=getattr(exc, "error_code", "alignment_build_failed"),
            error={"type": type(exc).__name__, "message": str(exc)},
        )

    def _reap(self) -> None:
        for run_id, task in list(self._tasks.items()):
            if task.done():
                with suppress(Exception):
                    task.result()
                self._tasks.pop(run_id, None)
