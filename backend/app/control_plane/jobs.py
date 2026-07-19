from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue

from .schemas import AttemptStatus, JobRecord, JobStatus, JobType
from .store import CreatedJob, LocalControlPlaneStore, stable_hash


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
    ) -> None:
        self.store = store
        self.job = created.job
        self.attempt = created.attempt
        self._execution_token = created.execution_token

    def cancel_requested(self) -> bool:
        return self.store.get_job(self.job.job_id).cancel_requested

    def checkpoint(self) -> None:
        self.store.heartbeat_attempt(self.attempt.attempt_id, self._execution_token)
        if self.cancel_requested():
            raise asyncio.CancelledError


class InProcessJobBackend:
    """Local first-class backend using the same durable Job/Attempt contracts as Team."""

    def __init__(
        self, store: LocalControlPlaneStore, handlers: dict[JobType, JobHandler] | None = None,
        *, concurrency: int = 2,
    ) -> None:
        self.store = store
        self.handlers = handlers or {}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    async def submit(self, request: JobRequest) -> JobHandle:
        created = self.store.create_job(
            workspace_id=request.workspace_id, project_id=request.project_id,
            job_type=request.job_type, queue_name=request.queue_name, request=request.payload,
            idempotency_key=request.idempotency_key, actor_id_hash=request.actor_id_hash,
            max_attempts=request.max_attempts,
        )
        if created.execution_token and created.job.job_id not in self._tasks:
            self._tasks[created.job.job_id] = asyncio.create_task(
                self._execute(created, request.payload), name=f"job:{created.job.job_id}",
            )
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
        self._tasks[created.job.job_id] = asyncio.create_task(
            self._execute(created, payload), name=f"job:{created.job.job_id}",
        )
        return JobHandle(created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id)

    async def get_status(self, job_id: str) -> JobRecord:
        return self.store.get_job(job_id)

    async def shutdown(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
        self._tasks.clear()

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
                context = JobExecutionContext(self.store, created)
                result_refs = await handler(context, payload)
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
            except asyncio.CancelledError:
                self.store.complete_attempt(
                    created.attempt.attempt_id, created.execution_token,
                    AttemptStatus.CANCELLED, error_code="job_cancelled",
                )
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
            except Exception:
                self.store.complete_attempt(
                    created.attempt.attempt_id, created.execution_token,
                    AttemptStatus.FAILED_TERMINAL, error_code="job_execution_failed",
                )
            finally:
                current = asyncio.current_task()
                if self._tasks.get(created.job.job_id) is current:
                    self._tasks.pop(created.job.job_id, None)
        if retry is not None:
            self._tasks[retry.job.job_id] = asyncio.create_task(
                self._execute(retry, retry.request), name=f"job:{retry.job.job_id}:retry",
            )


class RetryableJobError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


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
            max_attempts=request.max_attempts,
        )
        return JobHandle(created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id)

    async def cancel(self, job_id: str) -> None:
        getattr(self.store, "request_cancel")(job_id)

    async def retry(self, job_id: str) -> JobHandle:
        created = getattr(self.store, "create_manual_retry")(job_id)
        return JobHandle(created.job.job_id, created.job.domain_run_id or "", created.attempt.attempt_id)

    async def get_status(self, job_id: str) -> JobRecord:
        return getattr(self.store, "get_job")(job_id)
