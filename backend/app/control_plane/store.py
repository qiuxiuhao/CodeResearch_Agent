from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue

from .schemas import (
    ArtifactRecord, AttemptStatus, AuditEvent, JobAttempt, JobRecord, JobStatus, JobType, OutboxEvent,
    ProjectMembership, WorkspaceMembership,
)


MIGRATION_ROOT = Path(__file__).with_name("migrations")
MIGRATIONS = {
    1: MIGRATION_ROOT / "001_control_plane.sql",
    2: MIGRATION_ROOT / "002_job_requests.sql",
}
TERMINAL_JOBS = {
    JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED,
    JobStatus.CANCELLED, JobStatus.DEAD,
}
JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.DISPATCHING, JobStatus.CANCELLING, JobStatus.FAILED},
    JobStatus.DISPATCHING: {JobStatus.DISPATCHED, JobStatus.QUEUED, JobStatus.FAILED},
    JobStatus.DISPATCHED: {JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.CANCELLING},
    JobStatus.RUNNING: {
        JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.RETRY_WAIT,
        JobStatus.CANCELLING, JobStatus.FAILED,
    },
    JobStatus.RETRY_WAIT: {JobStatus.QUEUED, JobStatus.DEAD, JobStatus.CANCELLING},
    JobStatus.CANCELLING: {JobStatus.CANCELLED, JobStatus.FAILED},
}
ATTEMPT_TRANSITIONS: dict[AttemptStatus, set[AttemptStatus]] = {
    AttemptStatus.CREATED: {
        AttemptStatus.DISPATCHED, AttemptStatus.CANCELLED, AttemptStatus.SUPERSEDED,
    },
    AttemptStatus.DISPATCHED: {
        AttemptStatus.CLAIMED, AttemptStatus.LOST, AttemptStatus.CANCELLED,
        AttemptStatus.SUPERSEDED,
    },
    AttemptStatus.CLAIMED: {
        AttemptStatus.RUNNING, AttemptStatus.LOST, AttemptStatus.CANCELLED,
        AttemptStatus.SUPERSEDED,
    },
    AttemptStatus.RUNNING: {
        AttemptStatus.SUCCEEDED, AttemptStatus.FAILED_RETRYABLE,
        AttemptStatus.FAILED_TERMINAL, AttemptStatus.CANCELLED, AttemptStatus.LOST,
        AttemptStatus.SUPERSEDED,
    },
}


class ControlPlaneError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CreatedJob:
    job: JobRecord
    attempt: JobAttempt
    outbox: OutboxEvent
    execution_token: str
    request: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ClaimedOutbox:
    event: OutboxEvent
    claim_token: str


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def message_deduplication_key(
    job_id: str, attempt_number: int, task_schema_version: int, request_hash: str,
) -> str:
    return stable_hash(f"{job_id}:{attempt_number}:{task_schema_version}:{request_hash}")


class LocalControlPlaneStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            latest = max(MIGRATIONS)
            if version > latest:
                raise ControlPlaneError("control_plane_schema_too_new")
            for target in range(version + 1, latest + 1):
                connection.executescript(MIGRATIONS[target].read_text(encoding="utf-8"))

    def create_job(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        job_type: JobType,
        queue_name: str,
        request: dict[str, JsonValue],
        idempotency_key: str,
        actor_id_hash: str,
        domain_run_id: str | None = None,
        retry_of_job_id: str | None = None,
        max_attempts: int = 3,
        task_schema_version: int = 1,
    ) -> CreatedJob:
        self.migrate()
        now = datetime.now(UTC)
        request_json = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        request_hash = stable_hash(request_json)
        idempotency_hash = stable_hash(idempotency_key)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT job_json FROM jobs WHERE workspace_id=? AND idempotency_key_hash=?",
                (workspace_id, idempotency_hash),
            ).fetchone()
            if existing:
                job = JobRecord.model_validate_json(existing[0])
                if job.request_hash != request_hash:
                    raise ControlPlaneError("idempotency_key_conflict")
                attempt = self._get_attempt_in(connection, job.job_id, job.current_attempt_number)
                outbox = self._get_outbox_for_attempt(connection, attempt.attempt_id)
                stored_request = self._get_job_request_in(connection, job.job_id)
                return CreatedJob(job, attempt, outbox, "", stored_request)
            job_id = f"job_{uuid4().hex}"
            attempt_id = f"attempt_{uuid4().hex}"
            domain_run_id = domain_run_id or f"run_{uuid4().hex}"
            execution_token = secrets.token_urlsafe(32)
            execution_token_hash = stable_hash(execution_token)
            job = JobRecord(
                job_id=job_id, workspace_id=workspace_id, project_id=project_id,
                job_type=job_type, queue_name=queue_name, domain_run_id=domain_run_id,
                retry_of_job_id=retry_of_job_id, max_attempts=max_attempts,
                idempotency_key_hash=idempotency_hash, request_hash=request_hash,
                task_schema_version=task_schema_version, created_at=now, updated_at=now,
            )
            attempt = JobAttempt(
                attempt_id=attempt_id, job_id=job_id, attempt_number=1,
                execution_token_hash=execution_token_hash, created_at=now, updated_at=now,
            )
            outbox = self._new_outbox(job, attempt, request, now)
            connection.execute(
                "INSERT INTO domain_runs VALUES(?,?,?,?,?,?,?,?)",
                (domain_run_id, workspace_id, project_id, job_type, "queued", request_hash, _iso(now), _iso(now)),
            )
            self._insert_job(connection, job)
            connection.execute(
                "INSERT INTO job_requests VALUES(?,?,?,?,?,?)",
                (job_id, workspace_id, project_id, request_hash, request_json, _iso(now)),
            )
            self._insert_attempt(connection, attempt)
            self._insert_outbox(connection, outbox)
            audit = AuditEvent(
                audit_event_id=f"audit_{uuid4().hex}", workspace_id=workspace_id,
                project_id=project_id, actor_id_hash=actor_id_hash, action="job.create",
                object_type="job", object_id=job_id, outcome="succeeded",
                reason_code="job_created", occurred_at=now,
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    audit.audit_event_id, workspace_id, project_id, actor_id_hash, audit.action,
                    audit.object_type, job_id, audit.outcome, audit.reason_code,
                    audit.model_dump_json(), _iso(now),
                ),
            )
            connection.commit()
        return CreatedJob(job, attempt, outbox, execution_token, request)

    def create_workspace(self, workspace_id: str, name: str, owner_user_id: str) -> None:
        self.migrate()
        now = datetime.now(UTC)
        membership = WorkspaceMembership(
            workspace_id=workspace_id, user_id=owner_user_id, role="owner",
            created_at=now, updated_at=now,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO workspaces VALUES(?,?,?,?,?)",
                (workspace_id, name, "active", _iso(now), _iso(now)),
            )
            connection.execute(
                "INSERT INTO workspace_memberships VALUES(?,?,?,?,?)",
                (workspace_id, owner_user_id, "owner", "active", membership.model_dump_json()),
            )
            connection.commit()

    def create_project(
        self, project_id: str, workspace_id: str, name: str, owner_user_id: str,
    ) -> None:
        self.migrate()
        now = datetime.now(UTC)
        membership = ProjectMembership(
            project_id=project_id, workspace_id=workspace_id, user_id=owner_user_id,
            role="project_owner", created_at=now, updated_at=now,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            workspace = connection.execute(
                "SELECT status FROM workspaces WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
            if not workspace or workspace["status"] != "active":
                raise ControlPlaneError("workspace_not_active")
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?,?)",
                (project_id, workspace_id, name, "active", _iso(now), _iso(now)),
            )
            connection.execute(
                "INSERT INTO project_memberships VALUES(?,?,?,?,?,?)",
                (
                    project_id, workspace_id, owner_user_id, "project_owner", "active",
                    membership.model_dump_json(),
                ),
            )
            connection.commit()

    def list_workspaces_for_user(self, user_id: str) -> list[dict[str, str]]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT w.workspace_id,w.name,w.status,m.role
                   FROM workspaces w JOIN workspace_memberships m USING(workspace_id)
                   WHERE m.user_id=? AND m.status='active' AND w.status='active'
                   ORDER BY w.name,w.workspace_id""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_projects_for_user(self, user_id: str, workspace_id: str) -> list[dict[str, str]]:
        workspace, _ = self.get_memberships(user_id, workspace_id, None)
        with self._connect() as connection:
            if workspace.role in {"owner", "admin"}:
                rows = connection.execute(
                    """SELECT project_id,workspace_id,name,status,NULL AS role
                       FROM projects WHERE workspace_id=? AND status='active'
                       ORDER BY name,project_id""",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT p.project_id,p.workspace_id,p.name,p.status,m.role
                       FROM projects p JOIN project_memberships m USING(project_id,workspace_id)
                       WHERE p.workspace_id=? AND p.status='active' AND m.user_id=?
                         AND m.status='active' ORDER BY p.name,p.project_id""",
                    (workspace_id, user_id),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_jobs(self, workspace_id: str, project_id: str, *, limit: int = 100) -> list[JobRecord]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT job_json FROM jobs WHERE workspace_id=? AND project_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (workspace_id, project_id, limit),
            ).fetchall()
        return [JobRecord.model_validate_json(row[0]) for row in rows]

    def get_memberships(
        self, user_id: str, workspace_id: str, project_id: str | None,
    ) -> tuple[WorkspaceMembership, ProjectMembership | None]:
        self.migrate()
        with self._connect() as connection:
            workspace_row = connection.execute(
                """SELECT membership_json FROM workspace_memberships
                   WHERE workspace_id=? AND user_id=? AND status='active'""",
                (workspace_id, user_id),
            ).fetchone()
            project_row = None
            if project_id:
                project_row = connection.execute(
                    """SELECT membership_json FROM project_memberships
                       WHERE project_id=? AND workspace_id=? AND user_id=? AND status='active'""",
                    (project_id, workspace_id, user_id),
                ).fetchone()
        if not workspace_row:
            raise ControlPlaneError("workspace_access_denied")
        workspace = WorkspaceMembership.model_validate_json(workspace_row[0])
        project = ProjectMembership.model_validate_json(project_row[0]) if project_row else None
        return workspace, project

    def get_explicit_permissions(
        self, user_id: str, workspace_id: str, project_id: str | None,
    ) -> frozenset[str]:
        if project_id is None:
            return frozenset()
        now = _iso(datetime.now(UTC))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT permission,grant_json FROM project_access_grants
                   WHERE workspace_id=? AND project_id=? AND user_id=?""",
                (workspace_id, project_id, user_id),
            ).fetchall()
        permissions: set[str] = set()
        for row in rows:
            grant = json.loads(row["grant_json"])
            expires_at = grant.get("expires_at")
            if expires_at is None or expires_at > now:
                permissions.add(str(row["permission"]))
        return frozenset(permissions)

    def save_artifact(self, artifact: ArtifactRecord) -> None:
        self.migrate()
        transitions = {
            "staging": {"quarantined", "rejected", "orphaned"},
            "quarantined": {"validating", "rejected", "orphaned"},
            "validating": {"available", "rejected", "orphaned"},
            "available": {"deletion_requested"},
            "deletion_requested": {"deleted"},
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT artifact_json FROM artifacts WHERE artifact_id=?", (artifact.artifact_id,)
            ).fetchone()
            if row:
                current = ArtifactRecord.model_validate_json(row[0])
                if artifact.status not in transitions.get(current.status, set()):
                    raise ControlPlaneError("invalid_artifact_transition")
                connection.execute(
                    """UPDATE artifacts SET status=?,storage_key=?,content_hash=?,artifact_json=?,updated_at=?
                       WHERE artifact_id=?""",
                    (
                        artifact.status, artifact.storage_key, artifact.content_hash,
                        artifact.model_dump_json(), _iso(artifact.updated_at), artifact.artifact_id,
                    ),
                )
            else:
                if artifact.status != "staging":
                    raise ControlPlaneError("artifact_must_start_staging")
                connection.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        artifact.artifact_id, artifact.workspace_id, artifact.project_id,
                        artifact.status, artifact.storage_key, artifact.content_hash,
                        artifact.model_dump_json(), _iso(artifact.created_at), _iso(artifact.updated_at),
                    ),
                )
            connection.commit()

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT artifact_json FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
        if not row:
            raise ControlPlaneError("artifact_not_found")
        return ArtifactRecord.model_validate_json(row[0])

    def find_scoped_artifact_by_storage_key(
        self, workspace_id: str, project_id: str, storage_key: str,
    ) -> ArtifactRecord:
        """Compatibility lookup for persisted task-schema-v1 requests only."""
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT artifact_json FROM artifacts
                   WHERE workspace_id=? AND project_id=? AND storage_key=? LIMIT 2""",
                (workspace_id, project_id, storage_key),
            ).fetchall()
        if len(rows) != 1:
            raise ControlPlaneError("legacy_artifact_payload_unverifiable")
        return ArtifactRecord.model_validate_json(rows[0][0])

    def list_artifacts(
        self, workspace_id: str, project_id: str, *, limit: int = 100,
    ) -> list[ArtifactRecord]:
        self.migrate()
        bounded = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT artifact_json FROM artifacts
                   WHERE workspace_id=? AND project_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (workspace_id, project_id, bounded),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row[0]) for row in rows]

    def list_artifacts_for_maintenance(
        self,
        workspace_id: str,
        project_id: str,
        *,
        statuses: tuple[str, ...] = ("staging", "rejected", "orphaned"),
        limit: int = 1000,
    ) -> list[ArtifactRecord]:
        """Return only explicitly owned artifacts; unknown staging files are never included."""
        self.migrate()
        if not statuses:
            return []
        bounded = max(1, min(limit, 5000))
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT artifact_json FROM artifacts
                    WHERE workspace_id=? AND project_id=? AND status IN ({placeholders})
                    ORDER BY updated_at LIMIT ?""",
                (workspace_id, project_id, *statuses, bounded),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row[0]) for row in rows]

    def list_available_artifacts(
        self, workspace_id: str, project_id: str, *, limit: int = 5000,
    ) -> list[ArtifactRecord]:
        self.migrate()
        bounded = max(1, min(limit, 5000))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT artifact_json FROM artifacts
                   WHERE workspace_id=? AND project_id=? AND status='available'
                   ORDER BY artifact_id LIMIT ?""",
                (workspace_id, project_id, bounded),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row[0]) for row in rows]

    def get_job(self, job_id: str) -> JobRecord:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute("SELECT job_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise ControlPlaneError("job_not_found")
        return JobRecord.model_validate_json(row[0])

    def get_attempt(self, attempt_id: str) -> JobAttempt:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempt_json FROM job_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
        if not row:
            raise ControlPlaneError("attempt_not_found")
        return JobAttempt.model_validate_json(row[0])

    def transition_attempt(
        self,
        attempt_id: str,
        execution_token: str,
        target: AttemptStatus,
        *,
        worker_id_hash: str | None = None,
        celery_task_id: str | None = None,
    ) -> JobAttempt:
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempt_json FROM job_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if not row:
                raise ControlPlaneError("attempt_not_found")
            attempt = JobAttempt.model_validate_json(row[0])
            if not secrets.compare_digest(attempt.execution_token_hash, stable_hash(execution_token)):
                raise ControlPlaneError("stale_execution_token")
            if target not in ATTEMPT_TRANSITIONS.get(attempt.status, set()):
                raise ControlPlaneError("invalid_attempt_transition")
            values = attempt.model_dump()
            values.update(status=target, updated_at=now)
            if worker_id_hash is not None:
                values["worker_id_hash"] = worker_id_hash
            if celery_task_id is not None:
                values["celery_task_id"] = celery_task_id
            if target in {AttemptStatus.CLAIMED, AttemptStatus.RUNNING}:
                values["heartbeat_at"] = now
            if target is AttemptStatus.RUNNING:
                values["started_at"] = now
            updated = JobAttempt.model_validate(values)
            connection.execute(
                "UPDATE job_attempts SET status=?,attempt_json=?,updated_at=? WHERE attempt_id=?",
                (target, updated.model_dump_json(), _iso(now), attempt_id),
            )
            connection.commit()
        return updated

    def heartbeat_attempt(self, attempt_id: str, execution_token: str) -> JobAttempt:
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempt_json FROM job_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if not row:
                raise ControlPlaneError("attempt_not_found")
            attempt = JobAttempt.model_validate_json(row[0])
            if not secrets.compare_digest(attempt.execution_token_hash, stable_hash(execution_token)):
                raise ControlPlaneError("stale_execution_token")
            if attempt.status not in {AttemptStatus.CLAIMED, AttemptStatus.RUNNING}:
                raise ControlPlaneError("attempt_not_heartbeat_eligible")
            updated = attempt.model_copy(update={"heartbeat_at": now, "updated_at": now})
            connection.execute(
                "UPDATE job_attempts SET attempt_json=?,updated_at=? WHERE attempt_id=?",
                (updated.model_dump_json(), _iso(now), attempt_id),
            )
            connection.commit()
        return updated

    def transition_job(
        self, job_id: str, target: JobStatus, *, error_code: str | None = None,
        expected_revision: int | None = None,
    ) -> JobRecord:
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT job_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise ControlPlaneError("job_not_found")
            job = JobRecord.model_validate_json(row[0])
            if expected_revision is not None and job.revision != expected_revision:
                raise ControlPlaneError("stale_job_revision")
            if job.status in TERMINAL_JOBS or target not in JOB_TRANSITIONS.get(job.status, set()):
                raise ControlPlaneError("invalid_job_transition")
            data = job.model_dump()
            data.update(
                status=target, error_code=error_code, updated_at=now,
                finished_at=now if target in TERMINAL_JOBS else None, revision=job.revision + 1,
            )
            if target is JobStatus.RUNNING and job.started_at is None:
                data["started_at"] = now
            updated = JobRecord.model_validate(data)
            self._update_job(connection, updated)
            connection.commit()
        return updated

    def complete_attempt(
        self, attempt_id: str, execution_token: str, status: AttemptStatus,
        *, error_code: str | None = None, result_artifact_ref_ids: list[str] | None = None,
    ) -> tuple[JobAttempt, JobRecord]:
        allowed = {
            AttemptStatus.SUCCEEDED, AttemptStatus.FAILED_RETRYABLE,
            AttemptStatus.FAILED_TERMINAL, AttemptStatus.CANCELLED, AttemptStatus.LOST,
        }
        if status not in allowed:
            raise ControlPlaneError("invalid_attempt_terminal_status")
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempt_json FROM job_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if not row:
                raise ControlPlaneError("attempt_not_found")
            attempt = JobAttempt.model_validate_json(row[0])
            if not secrets.compare_digest(attempt.execution_token_hash, stable_hash(execution_token)):
                raise ControlPlaneError("stale_execution_token")
            job_row = connection.execute("SELECT job_json FROM jobs WHERE job_id=?", (attempt.job_id,)).fetchone()
            job = JobRecord.model_validate_json(job_row[0])
            if job.current_attempt_number != attempt.attempt_number:
                raise ControlPlaneError("late_attempt_result")
            # Direct store callers from the v1 compatibility boundary can own a Job-level
            # running lease without separately persisting every intermediate Attempt state.
            # The unified runtimes still record dispatched/claimed/running, while this narrow
            # compatibility path permits a created Attempt to be finalized exactly once.
            if (
                status not in ATTEMPT_TRANSITIONS.get(attempt.status, set())
                and attempt.status is not AttemptStatus.CREATED
            ):
                raise ControlPlaneError("invalid_attempt_transition")
            attempt_data = attempt.model_dump()
            attempt_data.update(
                status=status, error_code=error_code,
                retryable=status is AttemptStatus.FAILED_RETRYABLE,
                finished_at=now, updated_at=now,
            )
            updated_attempt = JobAttempt.model_validate(attempt_data)
            connection.execute(
                "UPDATE job_attempts SET status=?,attempt_json=?,updated_at=? WHERE attempt_id=?",
                (status, updated_attempt.model_dump_json(), _iso(now), attempt_id),
            )
            target = {
                AttemptStatus.SUCCEEDED: JobStatus.COMPLETED,
                AttemptStatus.FAILED_RETRYABLE: JobStatus.RETRY_WAIT,
                AttemptStatus.FAILED_TERMINAL: JobStatus.FAILED,
                AttemptStatus.CANCELLED: JobStatus.CANCELLED,
                AttemptStatus.LOST: JobStatus.RETRY_WAIT,
            }[status]
            job_data = job.model_dump()
            job_data.update(
                status=target, retryable=target is JobStatus.RETRY_WAIT, error_code=error_code,
                finished_at=now if target in TERMINAL_JOBS else None,
                updated_at=now, revision=job.revision + 1,
                result_artifact_ref_ids=result_artifact_ref_ids or job.result_artifact_ref_ids,
            )
            updated_job = JobRecord.model_validate(job_data)
            self._update_job(connection, updated_job)
            connection.commit()
        return updated_attempt, updated_job

    def create_retry_attempt(self, job_id: str) -> CreatedJob:
        self.migrate()
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT job_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise ControlPlaneError("job_not_found")
            job = JobRecord.model_validate_json(row[0])
            if job.status is not JobStatus.RETRY_WAIT:
                raise ControlPlaneError("job_not_retry_wait")
            if job.current_attempt_number >= job.max_attempts:
                data = job.model_dump()
                data.update(status=JobStatus.DEAD, finished_at=now, updated_at=now, revision=job.revision + 1)
                dead = JobRecord.model_validate(data)
                self._update_job(connection, dead)
                connection.commit()
                raise ControlPlaneError("job_attempts_exhausted")
            attempt = JobAttempt(
                attempt_id=f"attempt_{uuid4().hex}", job_id=job_id,
                attempt_number=job.current_attempt_number + 1,
                execution_token_hash=stable_hash(token), created_at=now, updated_at=now,
            )
            job_data = job.model_dump()
            job_data.update(
                status=JobStatus.QUEUED, current_attempt_number=attempt.attempt_number,
                retryable=False, error_code=None, updated_at=now, revision=job.revision + 1,
            )
            updated_job = JobRecord.model_validate(job_data)
            request = self._get_job_request_in(connection, job_id)
            outbox = self._new_outbox(updated_job, attempt, request, now)
            self._insert_attempt(connection, attempt)
            self._insert_outbox(connection, outbox)
            self._update_job(connection, updated_job)
            connection.commit()
        return CreatedJob(updated_job, attempt, outbox, token, request)

    def create_manual_retry(self, job_id: str, actor_id_hash: str = "system") -> CreatedJob:
        job = self.get_job(job_id)
        if job.status not in TERMINAL_JOBS:
            raise ControlPlaneError("manual_retry_requires_terminal_job")
        with self._connect() as connection:
            request = self._get_job_request_in(connection, job_id)
        return self.create_job(
            workspace_id=job.workspace_id, project_id=job.project_id, job_type=job.job_type,
            queue_name=job.queue_name, request=request,
            idempotency_key=f"manual-retry:{job_id}:{uuid4().hex}",
            actor_id_hash=actor_id_hash, retry_of_job_id=job_id,
            max_attempts=job.max_attempts, task_schema_version=job.task_schema_version,
        )

    def recover_incomplete_jobs(self) -> list[CreatedJob]:
        """Atomically supersede process-owned attempts and create restart attempts."""
        self.migrate()
        now = datetime.now(UTC)
        recovered: list[CreatedJob] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT job_json FROM jobs WHERE status NOT IN ('completed','partial','failed','cancelled','dead') "
                "ORDER BY created_at"
            ).fetchall()
            for row in rows:
                job = JobRecord.model_validate_json(row[0])
                attempt = self._get_attempt_in(
                    connection, job.job_id, job.current_attempt_number,
                )
                if attempt.status in {
                    AttemptStatus.CREATED, AttemptStatus.DISPATCHED,
                    AttemptStatus.CLAIMED, AttemptStatus.RUNNING,
                }:
                    attempt_status = (
                        AttemptStatus.SUPERSEDED
                        if attempt.status is AttemptStatus.CREATED
                        else AttemptStatus.LOST
                    )
                    updated_attempt = attempt.model_copy(update={
                        "status": attempt_status,
                        "error_code": "application_restart",
                        "retryable": True,
                        "finished_at": now,
                        "updated_at": now,
                    })
                    connection.execute(
                        "UPDATE job_attempts SET status=?,attempt_json=?,updated_at=? WHERE attempt_id=?",
                        (
                            attempt_status, updated_attempt.model_dump_json(),
                            _iso(now), attempt.attempt_id,
                        ),
                    )
                outbox_row = connection.execute(
                    "SELECT outbox_json FROM outbox_events WHERE attempt_id=?",
                    (attempt.attempt_id,),
                ).fetchone()
                if outbox_row:
                    event = OutboxEvent.model_validate_json(outbox_row[0])
                    if event.status != "failed":
                        failed_event = event.model_copy(update={
                            "status": "failed",
                            "claim_token_hash": None,
                            "lease_owner_hash": None,
                            "lease_until": None,
                            "last_publish_error_code": "attempt_superseded_on_restart",
                            "updated_at": now,
                        })
                        connection.execute(
                            """UPDATE outbox_events SET status='failed',claim_token_hash=NULL,
                               lease_owner_hash=NULL,lease_until=NULL,last_publish_error_code=?,
                               outbox_json=?,updated_at=? WHERE outbox_event_id=?""",
                            (
                                "attempt_superseded_on_restart", failed_event.model_dump_json(),
                                _iso(now), event.outbox_event_id,
                            ),
                        )
                if job.status is JobStatus.CANCELLING:
                    cancelled = job.model_copy(update={
                        "status": JobStatus.CANCELLED,
                        "cancel_requested": True,
                        "retryable": False,
                        "error_code": "job_cancelled_during_restart",
                        "finished_at": now,
                        "updated_at": now,
                        "revision": job.revision + 1,
                    })
                    self._update_job(connection, cancelled)
                    continue
                if job.current_attempt_number >= job.max_attempts:
                    dead = job.model_copy(update={
                        "status": JobStatus.DEAD,
                        "retryable": False,
                        "error_code": "job_attempts_exhausted_after_restart",
                        "finished_at": now,
                        "updated_at": now,
                        "revision": job.revision + 1,
                    })
                    self._update_job(connection, dead)
                    continue
                token = secrets.token_urlsafe(32)
                next_attempt = JobAttempt(
                    attempt_id=f"attempt_{uuid4().hex}", job_id=job.job_id,
                    attempt_number=job.current_attempt_number + 1,
                    execution_token_hash=stable_hash(token), created_at=now, updated_at=now,
                )
                queued = job.model_copy(update={
                    "status": JobStatus.QUEUED,
                    "current_attempt_number": next_attempt.attempt_number,
                    "cancel_requested": False,
                    "retryable": False,
                    "error_code": None,
                    "finished_at": None,
                    "updated_at": now,
                    "revision": job.revision + 1,
                })
                request = self._get_job_request_in(connection, job.job_id)
                outbox = self._new_outbox(queued, next_attempt, request, now)
                self._insert_attempt(connection, next_attempt)
                self._insert_outbox(connection, outbox)
                self._update_job(connection, queued)
                recovered.append(CreatedJob(queued, next_attempt, outbox, token, request))
            connection.commit()
        return recovered

    def request_cancel(self, job_id: str) -> JobRecord:
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT job_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise ControlPlaneError("job_not_found")
            job = JobRecord.model_validate_json(row[0])
            if job.status in TERMINAL_JOBS:
                return job
            if JobStatus.CANCELLING not in JOB_TRANSITIONS.get(job.status, set()):
                raise ControlPlaneError("job_cannot_cancel")
            data = job.model_dump()
            data.update(
                status=JobStatus.CANCELLING, cancel_requested=True,
                updated_at=now, revision=job.revision + 1,
            )
            updated = JobRecord.model_validate(data)
            self._update_job(connection, updated)
            connection.commit()
        return updated

    def claim_outbox(
        self, dispatcher_id: str, *, batch_size: int = 10, lease_seconds: int = 30,
    ) -> list[ClaimedOutbox]:
        self.migrate()
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        claimed: list[ClaimedOutbox] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT outbox_json FROM outbox_events
                   WHERE (status='pending' OR (status='publishing' AND lease_until<?))
                     AND (next_retry_at IS NULL OR next_retry_at<=?)
                   ORDER BY created_at LIMIT ?""",
                (_iso(now), _iso(now), batch_size),
            ).fetchall()
            for row in rows:
                event = OutboxEvent.model_validate_json(row[0])
                claim_token = secrets.token_urlsafe(32)
                data = event.model_dump()
                data.update(
                    status="publishing", claim_token_hash=stable_hash(claim_token),
                    lease_owner_hash=stable_hash(dispatcher_id), lease_until=lease_until,
                    publish_attempt=event.publish_attempt + 1, updated_at=now,
                )
                updated = OutboxEvent.model_validate(data)
                connection.execute(
                    """UPDATE outbox_events SET status='publishing',claim_token_hash=?,lease_owner_hash=?,
                       lease_until=?,publish_attempt=?,outbox_json=?,updated_at=? WHERE outbox_event_id=?""",
                    (
                        updated.claim_token_hash, updated.lease_owner_hash, _iso(lease_until),
                        updated.publish_attempt, updated.model_dump_json(), _iso(now), event.outbox_event_id,
                    ),
                )
                claimed.append(ClaimedOutbox(updated, claim_token))
            connection.commit()
        return claimed

    def mark_outbox_published(self, event_id: str, claim_token: str, message_id: str) -> OutboxEvent:
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT outbox_json FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
            if not row:
                raise ControlPlaneError("outbox_not_found")
            event = OutboxEvent.model_validate_json(row[0])
            if event.status != "publishing" or not event.claim_token_hash:
                raise ControlPlaneError("outbox_not_claimed")
            if not secrets.compare_digest(event.claim_token_hash, stable_hash(claim_token)):
                raise ControlPlaneError("outbox_claim_lost")
            data = event.model_dump()
            data.update(
                status="published", published_message_id=message_id, claim_token_hash=None,
                lease_owner_hash=None, lease_until=None, updated_at=now,
            )
            updated = OutboxEvent.model_validate(data)
            connection.execute(
                """UPDATE outbox_events SET status='published',claim_token_hash=NULL,
                   lease_owner_hash=NULL,lease_until=NULL,outbox_json=?,updated_at=?
                   WHERE outbox_event_id=?""",
                (updated.model_dump_json(), _iso(now), event_id),
            )
            connection.commit()
        return updated

    def mark_outbox_publish_failed(
        self, event_id: str, claim_token: str, error_code: str, *, retry_seconds: int = 5,
    ) -> OutboxEvent:
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT outbox_json FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
            if not row:
                raise ControlPlaneError("outbox_not_found")
            event = OutboxEvent.model_validate_json(row[0])
            if (
                event.status != "publishing" or not event.claim_token_hash
                or not secrets.compare_digest(event.claim_token_hash, stable_hash(claim_token))
            ):
                raise ControlPlaneError("outbox_claim_lost")
            updated = event.model_copy(update={
                "status": "pending",
                "claim_token_hash": None,
                "lease_owner_hash": None,
                "lease_until": None,
                "last_publish_error_code": error_code,
                "next_retry_at": now + timedelta(seconds=max(1, retry_seconds)),
                "updated_at": now,
            })
            connection.execute(
                """UPDATE outbox_events SET status='pending',claim_token_hash=NULL,
                   lease_owner_hash=NULL,lease_until=NULL,last_publish_error_code=?,next_retry_at=?,
                   outbox_json=?,updated_at=? WHERE outbox_event_id=?""",
                (
                    error_code, _iso(updated.next_retry_at), updated.model_dump_json(),
                    _iso(now), event_id,
                ),
            )
            connection.commit()
        return updated

    def mark_outbox_consumed_local(self, event_id: str) -> OutboxEvent:
        """Acknowledge the durable dispatch record without a broker in Local profile."""
        self.migrate()
        now = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT outbox_json FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
            if not row:
                raise ControlPlaneError("outbox_not_found")
            event = OutboxEvent.model_validate_json(row[0])
            if event.status == "published":
                return event
            if event.status != "pending":
                raise ControlPlaneError("outbox_not_pending")
            updated = event.model_copy(update={
                "status": "published",
                "published_message_id": f"local:{event.message_deduplication_key}",
                "updated_at": now,
            })
            connection.execute(
                "UPDATE outbox_events SET status='published',outbox_json=?,updated_at=? WHERE outbox_event_id=?",
                (updated.model_dump_json(), _iso(now), event_id),
            )
            connection.commit()
        return updated

    def list_attempts(self, job_id: str) -> list[JobAttempt]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT attempt_json FROM job_attempts WHERE job_id=? ORDER BY attempt_number", (job_id,)
            ).fetchall()
        return [JobAttempt.model_validate_json(row[0]) for row in rows]

    def _new_outbox(
        self, job: JobRecord, attempt: JobAttempt, request: dict[str, JsonValue], now: datetime,
    ) -> OutboxEvent:
        return OutboxEvent(
            outbox_event_id=f"outbox_{uuid4().hex}", aggregate_id=job.job_id,
            job_id=job.job_id, attempt_id=attempt.attempt_id,
            attempt_number=attempt.attempt_number, task_schema_version=job.task_schema_version,
            request_hash=job.request_hash,
            message_deduplication_key=message_deduplication_key(
                job.job_id, attempt.attempt_number, job.task_schema_version, job.request_hash,
            ),
            payload={
                "job_id": job.job_id,
                "attempt_id": attempt.attempt_id,
                "attempt_number": attempt.attempt_number,
                "job_type": job.job_type,
                "request_hash": job.request_hash,
                "task_schema_version": job.task_schema_version,
            },
            created_at=now, updated_at=now,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        return connection

    @staticmethod
    def _insert_job(connection: sqlite3.Connection, job: JobRecord) -> None:
        connection.execute(
            """INSERT INTO jobs(
                 job_id,workspace_id,project_id,job_type,queue_name,priority,status,
                 current_attempt_number,idempotency_key_hash,request_hash,revision,
                 job_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.job_id, job.workspace_id, job.project_id, job.job_type, job.queue_name, job.priority,
                job.status, job.current_attempt_number, job.idempotency_key_hash,
                job.request_hash, job.revision, job.model_dump_json(), _iso(job.created_at),
                _iso(job.updated_at),
            ),
        )

    @staticmethod
    def _update_job(connection: sqlite3.Connection, job: JobRecord) -> None:
        connection.execute(
            """UPDATE jobs SET status=?,current_attempt_number=?,revision=?,job_json=?,updated_at=?
               WHERE job_id=?""",
            (
                job.status, job.current_attempt_number, job.revision,
                job.model_dump_json(), _iso(job.updated_at), job.job_id,
            ),
        )

    @staticmethod
    def _insert_attempt(connection: sqlite3.Connection, attempt: JobAttempt) -> None:
        connection.execute(
            "INSERT INTO job_attempts VALUES(?,?,?,?,?,?,?,?)",
            (
                attempt.attempt_id, attempt.job_id, attempt.attempt_number, attempt.status,
                attempt.execution_token_hash, attempt.model_dump_json(),
                _iso(attempt.created_at), _iso(attempt.updated_at),
            ),
        )

    @staticmethod
    def _insert_outbox(connection: sqlite3.Connection, event: OutboxEvent) -> None:
        connection.execute(
            """INSERT INTO outbox_events(
                 outbox_event_id,job_id,attempt_id,status,message_deduplication_key,
                 claim_token_hash,lease_owner_hash,lease_until,publish_attempt,
                 last_publish_error_code,next_retry_at,outbox_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event.outbox_event_id, event.job_id, event.attempt_id, event.status,
                event.message_deduplication_key, event.claim_token_hash, event.lease_owner_hash,
                _iso(event.lease_until), event.publish_attempt, event.last_publish_error_code,
                _iso(event.next_retry_at), event.model_dump_json(), _iso(event.created_at),
                _iso(event.updated_at),
            ),
        )

    @staticmethod
    def _get_attempt_in(connection: sqlite3.Connection, job_id: str, attempt_number: int) -> JobAttempt:
        row = connection.execute(
            "SELECT attempt_json FROM job_attempts WHERE job_id=? AND attempt_number=?",
            (job_id, attempt_number),
        ).fetchone()
        return JobAttempt.model_validate_json(row[0])

    @staticmethod
    def _get_outbox_for_attempt(connection: sqlite3.Connection, attempt_id: str) -> OutboxEvent:
        row = connection.execute(
            "SELECT outbox_json FROM outbox_events WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        return OutboxEvent.model_validate_json(row[0])

    @staticmethod
    def _get_job_request_in(connection: sqlite3.Connection, job_id: str) -> dict[str, JsonValue]:
        row = connection.execute(
            "SELECT request_json FROM job_requests WHERE job_id=?", (job_id,)
        ).fetchone()
        if not row:
            raise ControlPlaneError("job_request_not_found")
        value = json.loads(row[0])
        if not isinstance(value, dict):
            raise ControlPlaneError("job_request_invalid")
        return value


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None
