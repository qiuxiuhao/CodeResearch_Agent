from __future__ import annotations

from datetime import UTC, datetime
import sqlite3

import pytest

from backend.app.control_plane.schemas import AttemptStatus, JobRecord, JobStatus
from backend.app.control_plane.store import ControlPlaneError, LocalControlPlaneStore


def _created(tmp_path, *, max_attempts=3):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    created = store.create_job(
        workspace_id="workspace-a", project_id="project-a", job_type="analysis",
        queue_name="cra.analysis", request={"artifact_id": "artifact-a"},
        idempotency_key="request-123", actor_id_hash="actor", max_attempts=max_attempts,
    )
    return store, created


def _running(store, job_id):
    store.transition_job(job_id, JobStatus.DISPATCHING)
    store.transition_job(job_id, JobStatus.DISPATCHED)
    return store.transition_job(job_id, JobStatus.RUNNING)


def test_local_control_run_and_job_created_atomically(tmp_path):
    store, created = _created(tmp_path)
    assert created.job.domain_run_id
    with store._connect() as connection:
        assert connection.execute("SELECT count(*) FROM domain_runs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM job_attempts").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1


def test_existing_v1_control_plane_receives_job_requests_migration(tmp_path):
    path = tmp_path / "control.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 1")
    store = LocalControlPlaneStore(path)
    store.migrate()
    with store._connect() as connection:
        names = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "job_requests" in names
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_retryable_attempt_failure_moves_job_to_retry_wait(tmp_path):
    store, created = _created(tmp_path)
    _running(store, created.job.job_id)
    _, job = store.complete_attempt(
        created.attempt.attempt_id, created.execution_token,
        AttemptStatus.FAILED_RETRYABLE, error_code="provider_timeout",
    )
    assert job.status is JobStatus.RETRY_WAIT
    assert job.finished_at is None


def test_retry_wait_can_return_to_queued(tmp_path):
    store, created = _created(tmp_path)
    _running(store, created.job.job_id)
    store.complete_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.FAILED_RETRYABLE,
    )
    retried = store.create_retry_attempt(created.job.job_id)
    assert retried.job.status is JobStatus.QUEUED
    assert retried.attempt.attempt_number == 2
    assert len(store.list_attempts(created.job.job_id)) == 2


def test_terminal_failed_job_never_returns_to_queued(tmp_path):
    store, created = _created(tmp_path)
    _running(store, created.job.job_id)
    store.complete_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.FAILED_TERMINAL,
    )
    with pytest.raises(ControlPlaneError, match="job_not_retry_wait"):
        store.create_retry_attempt(created.job.job_id)
    with pytest.raises(ControlPlaneError, match="invalid_job_transition"):
        store.transition_job(created.job.job_id, JobStatus.QUEUED)


def test_attempt_failure_is_not_job_failure(tmp_path):
    store, created = _created(tmp_path)
    _running(store, created.job.job_id)
    attempt, job = store.complete_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.FAILED_RETRYABLE,
    )
    assert attempt.status is AttemptStatus.FAILED_RETRYABLE
    assert job.status is not JobStatus.FAILED


def test_manual_retry_creates_new_job(tmp_path):
    store, created = _created(tmp_path)
    _running(store, created.job.job_id)
    store.complete_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.FAILED_TERMINAL,
    )
    retried = store.create_manual_retry(created.job.job_id)
    assert retried.job.job_id != created.job.job_id
    assert retried.job.domain_run_id != created.job.domain_run_id
    assert retried.job.retry_of_job_id == created.job.job_id


def test_job_finished_at_only_set_on_terminal_status(tmp_path):
    store, created = _created(tmp_path)
    assert created.job.finished_at is None
    _running(store, created.job.job_id)
    _, job = store.complete_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.SUCCEEDED,
    )
    assert job.finished_at is not None
    with pytest.raises(ValueError):
        JobRecord.model_validate({**job.model_dump(), "status": "running"})


def test_local_attempt_lifecycle_and_outbox_are_completed(tmp_path):
    import asyncio

    from backend.app.control_plane.jobs import InProcessJobBackend, JobRequest

    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    seen = []

    async def handler(context, payload):
        context.checkpoint()
        seen.append(payload["artifact_id"])
        return []

    async def run():
        backend = InProcessJobBackend(store, {"analysis": handler})
        handle = await backend.submit(JobRequest(
            workspace_id="workspace-a", project_id="project-a", job_type="analysis",
            queue_name="cra.analysis", payload={"artifact_id": "artifact-a"},
            idempotency_key="request-456", actor_id_hash="actor",
        ))
        await backend.shutdown()
        return handle

    handle = asyncio.run(run())
    attempt = store.get_attempt(handle.attempt_id)
    assert attempt.status is AttemptStatus.SUCCEEDED
    assert attempt.started_at is not None
    assert attempt.heartbeat_at is not None
    with store._connect() as connection:
        row = connection.execute(
            "SELECT outbox_json FROM outbox_events WHERE attempt_id=?", (handle.attempt_id,)
        ).fetchone()
    from backend.app.control_plane.schemas import OutboxEvent
    outbox = OutboxEvent.model_validate_json(row[0])
    assert outbox.status == "published"
    assert outbox.published_message_id.startswith("local:")
    assert seen == ["artifact-a"]


def test_late_result_does_not_overwrite_new_attempt(tmp_path):
    store, created = _created(tmp_path)
    _running(store, created.job.job_id)
    store.complete_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.FAILED_RETRYABLE,
    )
    store.create_retry_attempt(created.job.job_id)
    with pytest.raises(ControlPlaneError, match="late_attempt_result"):
        store.complete_attempt(
            created.attempt.attempt_id, created.execution_token, AttemptStatus.SUCCEEDED,
        )


def test_execution_policy_rejects_invalid_limit_order():
    from backend.app.control_plane.schemas import JobExecutionPolicy

    with pytest.raises(ValueError):
        JobExecutionPolicy(
            job_type="analysis", business_deadline_seconds=60,
            soft_time_limit_seconds=30, hard_time_limit_seconds=70,
            broker_visibility_timeout_seconds=80, heartbeat_interval_seconds=5,
            lease_seconds=20, checkpoint_interval_seconds=10, max_stage_seconds=30,
        )


def test_inprocess_retryable_error_creates_new_attempt_and_completes(tmp_path):
    import asyncio

    from backend.app.control_plane.jobs import InProcessJobBackend, JobRequest, RetryableJobError

    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    calls = 0

    async def handler(context, payload):
        nonlocal calls
        calls += 1
        context.checkpoint()
        if calls == 1:
            raise RetryableJobError("temporary_failure")
        return ["artifact-result"]

    async def run():
        backend = InProcessJobBackend(store, {"maintenance": handler})
        handle = await backend.submit(JobRequest(
            workspace_id="workspace-a", project_id="project-a", job_type="maintenance",
            queue_name="cra.maintenance", payload={"action": "cleanup_staging"},
            idempotency_key="retryable-operation", actor_id_hash="actor",
        ))
        await backend.shutdown()
        return handle

    handle = asyncio.run(run())
    assert store.get_job(handle.job_id).status is JobStatus.COMPLETED
    assert len(store.list_attempts(handle.job_id)) == 2
    assert calls == 2
