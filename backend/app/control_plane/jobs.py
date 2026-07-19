from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue
from pydantic import ValidationError

from .schemas import AttemptStatus, JobRecord, JobStatus, JobType
from .artifacts import ArtifactSecurityError
from .store import ControlPlaneError, CreatedJob, LocalControlPlaneStore, stable_hash


JobHandler = Callable[["JobExecutionContext", dict[str, JsonValue]], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class JobRequest:
    workspace_id: str
    project_id: str | None
    job_type: JobType
    queue_name: str
    payload: dict[str, JsonValue]
    idempotency_key: str
    actor_id_hash: str
    max_attempts: int = 3
    task_schema_version: int = 1


@dataclass(frozen=True, slots=True)
class JobHandle:
    job_id: str
    domain_run_id: str
    attempt_id: str


class JobBackend(Protocol):
    async def submit(self, request: JobRequest) -> JobHandle: ...
    async def cancel(self, job_id: str) -> None: ...
    async def retry(self, job_id: str) -> JobHandle: ...
    async def get_status(self, job_id: str) -> JobRecord: ...


class JobExecutionContext:
    def __init__(
        self, store: LocalControlPlaneStore, created: CreatedJob,
        shutdown_requested: Callable[[], bool] | None = None,
        *, heartbeat_interval_seconds: float = 5.0,
    ) -> None:
        self.store = store
        self.job = created.job
        self.attempt = created.attempt
        self._execution_token = created.execution_token
        self._shutdown_requested = shutdown_requested or (lambda: False)
        self._heartbeat_interval_seconds = max(0.05, heartbeat_interval_seconds)
        self._last_checkpoint = 0.0

    def cancel_requested(self) -> bool:
        return self.store.get_job(self.job.job_id).cancel_requested

    def checkpoint(self) -> None:
        self.store.heartbeat_attempt(self.attempt.attempt_id, self._execution_token)
        self._last_checkpoint = time.monotonic()
        if self._shutdown_requested():
            raise JobShutdownRequested
        if self.cancel_requested():
            raise asyncio.CancelledError

    def checkpoint_if_due(self) -> None:
        if time.monotonic() - self._last_checkpoint >= self._heartbeat_interval_seconds:
            self.checkpoint()
            return
        if self._shutdown_requested():
            raise JobShutdownRequested
        if self.cancel_requested():
            raise asyncio.CancelledError


class InProcessJobBackend:
    """Local first-class backend using the same durable Job/Attempt contracts as Team."""

    def __init__(
        self, store: LocalControlPlaneStore, handlers: dict[JobType, JobHandler] | None = None,
        *, concurrency: int = 2, heartbeat_interval_seconds: float = 5.0,
    ) -> None:
        self.store = store
        self.handlers = handlers or {}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active: dict[str, CreatedJob] = {}
        self._accepting = True
        self._shutdown_requested = False
        self._started = False
        self._heartbeat_interval_seconds = max(0.05, heartbeat_interval_seconds)

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._accepting = True
        self._shutdown_requested = False
        for created in self.store.recover_incomplete_jobs():
            self._schedule(created, created.request)

    async def submit(self, request: JobRequest) -> JobHandle:
        if not self._accepting:
            raise ControlPlaneError("job_backend_shutting_down")
        created = self.store.create_job(
            workspace_id=request.workspace_id, project_id=request.project_id,
            job_type=request.job_type, queue_name=request.queue_name, request=request.payload,
            idempotency_key=request.idempotency_key, actor_id_hash=request.actor_id_hash,
            max_attempts=request.max_attempts, task_schema_version=request.task_schema_version,
        )
        if created.execution_token and created.job.job_id not in self._tasks:
            self._schedule(created, request.payload)
        return JobHandle(
            created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id,
        )

    async def cancel(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job.status in {
            JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.DEAD,
        }:
            return
        self.store.request_cancel(job_id)

    async def retry(self, job_id: str) -> JobHandle:
        created = self.store.create_manual_retry(job_id)
        payload = created.request
        if not self._accepting:
            raise ControlPlaneError("job_backend_shutting_down")
        self._schedule(created, payload)
        return JobHandle(created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id)

    async def get_status(self, job_id: str) -> JobRecord:
        return self.store.get_job(job_id)

    async def shutdown(self, *, grace_seconds: float = 15.0) -> None:
        self._accepting = False
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while self._tasks and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            await asyncio.wait(
                list(self._tasks.values()), timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
        self._shutdown_requested = True
        pending = set(self._tasks.values())
        if pending:
            _, pending = await asyncio.wait(pending, timeout=1.0)
            for task in pending:
                created = next(
                    (item for item in self._active.values() if self._tasks.get(item.job.job_id) is task),
                    None,
                )
                if created is not None:
                    self._finish_safely(
                        created, AttemptStatus.LOST, "application_shutdown",
                    )
                task.cancel()
            if pending:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True), timeout=1.0,
                    )
                except TimeoutError:
                    pass
        self._tasks.clear()
        self._active.clear()

    def _schedule(self, created: CreatedJob, payload: dict[str, JsonValue]) -> None:
        self._active[created.job.job_id] = created
        self._tasks[created.job.job_id] = asyncio.create_task(
            self._execute(created, payload), name=f"job:{created.job.job_id}",
        )

    async def _execute(self, created: CreatedJob, payload: dict[str, JsonValue]) -> None:
        retry: CreatedJob | None = None
        async with self._semaphore:
            handler = self.handlers.get(created.job.job_type)
            try:
                if self.store.get_job(created.job.job_id).status is JobStatus.CANCELLING:
                    self.store.complete_attempt(
                        created.attempt.attempt_id, created.execution_token,
                        AttemptStatus.CANCELLED, error_code="job_cancelled",
                    )
                    return
                self.store.transition_job(created.job.job_id, JobStatus.DISPATCHING)
                self.store.mark_outbox_consumed_local(created.outbox.outbox_event_id)
                self.store.transition_job(created.job.job_id, JobStatus.DISPATCHED)
                self.store.transition_attempt(
                    created.attempt.attempt_id, created.execution_token, AttemptStatus.DISPATCHED,
                )
                self.store.transition_attempt(
                    created.attempt.attempt_id, created.execution_token, AttemptStatus.CLAIMED,
                    worker_id_hash=stable_hash("local-in-process"),
                )
                self.store.transition_attempt(
                    created.attempt.attempt_id, created.execution_token, AttemptStatus.RUNNING,
                )
                self.store.transition_job(created.job.job_id, JobStatus.RUNNING)
                if not handler:
                    self.store.complete_attempt(
                        created.attempt.attempt_id, created.execution_token,
                        AttemptStatus.FAILED_TERMINAL, error_code="job_handler_missing",
                    )
                    return
                context = JobExecutionContext(
                    self.store, created, lambda: self._shutdown_requested,
                    heartbeat_interval_seconds=self._heartbeat_interval_seconds,
                )
                owner = asyncio.current_task()
                heartbeat = asyncio.create_task(
                    self._heartbeat(context, owner), name=f"heartbeat:{created.job.job_id}",
                )
                try:
                    result_refs = await handler(context, payload)
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                current = self.store.get_job(created.job.job_id)
                if current.status is JobStatus.CANCELLING:
                    self.store.complete_attempt(
                        created.attempt.attempt_id, created.execution_token,
                        AttemptStatus.CANCELLED, error_code="job_cancelled",
                    )
                else:
                    self.store.complete_attempt(
                        created.attempt.attempt_id, created.execution_token, AttemptStatus.SUCCEEDED,
                        result_artifact_ref_ids=result_refs,
                    )
            except JobShutdownRequested:
                self._finish_safely(created, AttemptStatus.LOST, "application_shutdown")
            except asyncio.CancelledError:
                status = AttemptStatus.LOST if self._shutdown_requested else AttemptStatus.CANCELLED
                code = "application_shutdown" if self._shutdown_requested else "job_cancelled"
                self._finish_safely(created, status, code)
            except RetryableJobError as exc:
                _, job = self.store.complete_attempt(
                    created.attempt.attempt_id, created.execution_token,
                    AttemptStatus.FAILED_RETRYABLE, error_code=exc.error_code,
                )
                if job.current_attempt_number < job.max_attempts:
                    retry = self.store.create_retry_attempt(job.job_id)
                else:
                    try:
                        self.store.create_retry_attempt(job.job_id)
                    except Exception:
                        pass
            except Exception as exc:
                status, code = classify_job_error(exc)
                if status is AttemptStatus.FAILED_RETRYABLE:
                    _, job = self.store.complete_attempt(
                        created.attempt.attempt_id, created.execution_token,
                        status, error_code=code,
                    )
                    if job.current_attempt_number < job.max_attempts:
                        retry = self.store.create_retry_attempt(job.job_id)
                    else:
                        try:
                            self.store.create_retry_attempt(job.job_id)
                        except ControlPlaneError:
                            pass
                else:
                    self._finish_safely(created, status, code)
            finally:
                current = asyncio.current_task()
                if self._tasks.get(created.job.job_id) is current:
                    self._tasks.pop(created.job.job_id, None)
                self._active.pop(created.job.job_id, None)
        if retry is not None:
            if not self._shutdown_requested:
                self._schedule(retry, retry.request)

    async def _heartbeat(
        self, context: JobExecutionContext, owner: asyncio.Task[None] | None,
    ) -> None:
        while True:
            await asyncio.sleep(context._heartbeat_interval_seconds)
            try:
                context.checkpoint()
            except JobShutdownRequested:
                if owner is not None:
                    owner.cancel()
                return
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                if owner is not None:
                    owner.cancel()
                return
            except Exception:
                if owner is not None:
                    owner.cancel()
                return

    def _finish_safely(
        self, created: CreatedJob, status: AttemptStatus, error_code: str,
    ) -> None:
        try:
            self.store.complete_attempt(
                created.attempt.attempt_id, created.execution_token,
                status, error_code=error_code,
            )
        except ControlPlaneError as exc:
            if exc.code not in {
                "late_attempt_result", "stale_execution_token", "invalid_attempt_transition",
            }:
                raise


class RetryableJobError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class JobShutdownRequested(RuntimeError):
    pass


def classify_job_error(exc: Exception) -> tuple[AttemptStatus, str]:
    if isinstance(exc, ControlPlaneError):
        retryable = exc.code in {"local_store_busy", "artifact_store_temporarily_unavailable"}
        return (
            AttemptStatus.FAILED_RETRYABLE if retryable else AttemptStatus.FAILED_TERMINAL,
            exc.code,
        )
    if isinstance(exc, ArtifactSecurityError):
        return AttemptStatus.FAILED_TERMINAL, exc.code
    if isinstance(exc, ValidationError):
        return AttemptStatus.FAILED_TERMINAL, "job_payload_invalid"
    if isinstance(exc, sqlite3.OperationalError) and any(
        marker in str(exc).casefold() for marker in ("locked", "busy")
    ):
        return AttemptStatus.FAILED_RETRYABLE, "local_store_busy"
    code = getattr(exc, "error_code", None)
    if isinstance(code, str) and code:
        return AttemptStatus.FAILED_TERMINAL, code
    message = str(exc)
    if message in {
        "research_run_failed", "alignment_run_failed", "evaluation_run_failed",
        "research_runtime_unavailable", "alignment_runtime_unavailable",
        "evaluation_runtime_unavailable", "live_evaluation_requires_explicit_v2_consent",
    }:
        return AttemptStatus.FAILED_TERMINAL, message
    return AttemptStatus.FAILED_TERMINAL, "job_internal_error"


class CeleryJobBackend:
    """Team submission adapter; Celery is transport, never the status authority."""

    def __init__(self, store: object) -> None:
        self.store = store

    async def submit(self, request: JobRequest) -> JobHandle:
        create = getattr(self.store, "create_job")
        created = create(
            workspace_id=request.workspace_id, project_id=request.project_id,
            job_type=request.job_type, queue_name=request.queue_name, request=request.payload,
            idempotency_key=request.idempotency_key, actor_id_hash=request.actor_id_hash,
            max_attempts=request.max_attempts, task_schema_version=request.task_schema_version,
        )
        return JobHandle(created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id)

    async def cancel(self, job_id: str) -> None:
        getattr(self.store, "request_cancel")(job_id)

    async def retry(self, job_id: str) -> JobHandle:
        created = getattr(self.store, "create_manual_retry")(job_id)
        return JobHandle(created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id)

    async def get_status(self, job_id: str) -> JobRecord:
        return getattr(self.store, "get_job")(job_id)
