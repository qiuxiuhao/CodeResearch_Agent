from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import JsonValue

from .schemas import JobAttempt, JobRecord, JobStatus, JobType, OutboxEvent
from .store import CreatedJob, ControlPlaneError, message_deduplication_key, stable_hash


TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED,
    JobStatus.CANCELLED, JobStatus.DEAD,
}


class PostgresControlPlaneStore:
    """Optional Team store entry point with explicit dependency and no Local fallback."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("team profile requires the 'team' dependency extra") from exc
        self._psycopg = psycopg

    def check_connectivity(self) -> None:
        with self._psycopg.connect(self.database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                cursor.fetchone()

    def reset_context(self, connection: object) -> None:
        execute = getattr(connection, "execute")
        execute("RESET ALL")

    def create_job(
        self, *, workspace_id: str, project_id: str | None, job_type: JobType,
        queue_name: str, request: dict[str, JsonValue], idempotency_key: str,
        actor_id_hash: str, domain_run_id: str | None = None,
        retry_of_job_id: str | None = None, max_attempts: int = 3,
        task_schema_version: int = 1,
    ) -> CreatedJob:
        now = datetime.now(UTC)
        request_json = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        request_hash = stable_hash(request_json)
        idempotency_hash = stable_hash(idempotency_key)
        execution_token = secrets.token_urlsafe(32)
        with self._psycopg.connect(self.database_url) as connection:
            connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))
            connection.execute("SELECT set_config('app.project_id',%s,true)", (project_id or "",))
            row = connection.execute(
                "SELECT job_json FROM cra_control.jobs WHERE workspace_id=%s AND idempotency_key_hash=%s",
                (workspace_id, idempotency_hash),
            ).fetchone()
            if row:
                job = JobRecord.model_validate(row[0])
                if job.request_hash != request_hash:
                    raise ControlPlaneError("idempotency_key_conflict")
                attempt_row = connection.execute(
                    "SELECT attempt_json FROM cra_control.job_attempts WHERE job_id=%s AND attempt_number=%s",
                    (job.job_id, job.current_attempt_number),
                ).fetchone()
                outbox_row = connection.execute(
                    "SELECT payload,message_deduplication_key,outbox_event_id,status,updated_at FROM cra_control.outbox_events WHERE attempt_id=%s",
                    (attempt_row[0]["attempt_id"],),
                ).fetchone()
                attempt = JobAttempt.model_validate(attempt_row[0])
                event = OutboxEvent(
                    outbox_event_id=outbox_row[2], aggregate_id=job.job_id, job_id=job.job_id,
                    attempt_id=attempt.attempt_id, attempt_number=attempt.attempt_number,
                    task_schema_version=job.task_schema_version, request_hash=job.request_hash,
                    message_deduplication_key=outbox_row[1], status=outbox_row[3],
                    payload=outbox_row[0], created_at=job.created_at, updated_at=outbox_row[4],
                )
                return CreatedJob(job, attempt, event, "", request)
            job_id = f"job_{uuid4().hex}"
            attempt_id = f"attempt_{uuid4().hex}"
            run_id = domain_run_id or f"run_{uuid4().hex}"
            job = JobRecord(
                job_id=job_id, workspace_id=workspace_id, project_id=project_id,
                job_type=job_type, queue_name=queue_name, domain_run_id=run_id,
                retry_of_job_id=retry_of_job_id, max_attempts=max_attempts,
                idempotency_key_hash=idempotency_hash, request_hash=request_hash,
                task_schema_version=task_schema_version, created_at=now, updated_at=now,
            )
            attempt = JobAttempt(
                attempt_id=attempt_id, job_id=job_id, attempt_number=1,
                execution_token_hash=stable_hash(execution_token), created_at=now, updated_at=now,
            )
            payload = {
                "job_id": job_id, "attempt_id": attempt_id, "attempt_number": 1,
                "job_type": job_type, "request_hash": request_hash,
                "task_schema_version": task_schema_version,
            }
            event = OutboxEvent(
                outbox_event_id=f"outbox_{uuid4().hex}", aggregate_id=job_id, job_id=job_id,
                attempt_id=attempt_id, attempt_number=1, task_schema_version=task_schema_version,
                request_hash=request_hash,
                message_deduplication_key=message_deduplication_key(
                    job_id, 1, task_schema_version, request_hash,
                ), payload=payload, created_at=now, updated_at=now,
            )
            connection.execute(
                """INSERT INTO cra_control.jobs(
                     job_id,workspace_id,project_id,job_type,domain_run_id,queue_name,resource_class,
                     status,priority,task_schema_version,handler_version,idempotency_key_hash,
                     request_hash,current_attempt_number,job_json,created_at,updated_at
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (
                    job_id,workspace_id,project_id,job_type,run_id,queue_name,job.resource_class,
                    job.status,job.priority,task_schema_version,job.handler_version,idempotency_hash,
                    request_hash,1,job.model_dump_json(),now,now,
                ),
            )
            connection.execute(
                "INSERT INTO cra_control.job_requests VALUES(%s,%s,%s,%s,%s::jsonb,%s)",
                (job_id,workspace_id,project_id,request_hash,request_json,now),
            )
            connection.execute(
                """INSERT INTO cra_control.job_attempts(
                     attempt_id,job_id,workspace_id,project_id,attempt_number,status,
                     execution_token_hash,task_schema_version,attempt_json
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (
                    attempt_id,job_id,workspace_id,project_id,1,attempt.status,
                    attempt.execution_token_hash,task_schema_version,attempt.model_dump_json(),
                ),
            )
            connection.execute(
                """INSERT INTO cra_control.outbox_events(
                     outbox_event_id,job_id,attempt_id,status,task_schema_version,
                     message_deduplication_key,publish_attempt,payload,updated_at
                   ) VALUES(%s,%s,%s,'pending',%s,%s,0,%s::jsonb,%s)""",
                (
                    event.outbox_event_id,job_id,attempt_id,task_schema_version,
                    event.message_deduplication_key,json.dumps(payload, sort_keys=True),now,
                ),
            )
            connection.commit()
        return CreatedJob(job, attempt, event, execution_token, request)

    def get_job(self, job_id: str) -> JobRecord:
        with self._psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT job_json FROM cra_control.jobs WHERE job_id=%s", (job_id,),
            ).fetchone()
        if not row:
            raise ControlPlaneError("job_not_found")
        return JobRecord.model_validate(row[0])

    def request_cancel(self, job_id: str) -> JobRecord:
        now = datetime.now(UTC)
        with self._psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT job_json FROM cra_control.jobs WHERE job_id=%s FOR UPDATE", (job_id,),
            ).fetchone()
            if not row:
                raise ControlPlaneError("job_not_found")
            job = JobRecord.model_validate(row[0])
            if job.status in TERMINAL_JOB_STATUSES:
                return job
            updated = job.model_copy(update={
                "status": JobStatus.CANCELLING,
                "cancel_requested": True,
                "updated_at": now,
                "revision": job.revision + 1,
            })
            connection.execute(
                """UPDATE cra_control.jobs SET status=%s,job_json=%s::jsonb,updated_at=%s
                   WHERE job_id=%s""",
                (updated.status, updated.model_dump_json(), now, job_id),
            )
            connection.commit()
        return updated

    def create_manual_retry(self, job_id: str, actor_id_hash: str = "system") -> CreatedJob:
        job = self.get_job(job_id)
        if job.status not in TERMINAL_JOB_STATUSES:
            raise ControlPlaneError("manual_retry_requires_terminal_job")
        with self._psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT request_json FROM cra_control.job_requests WHERE job_id=%s", (job_id,),
            ).fetchone()
        if not row or not isinstance(row[0], dict):
            raise ControlPlaneError("job_request_not_found")
        return self.create_job(
            workspace_id=job.workspace_id,
            project_id=job.project_id,
            job_type=job.job_type,
            queue_name=job.queue_name,
            request=row[0],
            idempotency_key=f"manual-retry:{job_id}:{uuid4().hex}",
            actor_id_hash=actor_id_hash,
            retry_of_job_id=job_id,
            max_attempts=job.max_attempts,
            task_schema_version=job.task_schema_version,
        )
