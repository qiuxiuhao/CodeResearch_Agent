from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.app.services.analysis_service import run_analysis

from .artifacts import S3ArtifactStore, validate_archive, validate_pdf_header
from .config import PlatformSettings
from .domain_handlers import AnalysisJobPayload
from .schemas import ArtifactRecord, AttemptStatus, JobAttempt, JobRecord, JobStatus
from .store import stable_hash


def execute_claimed_job(
    *, database_url: str, claim: tuple, worker_id_hash: str, celery_task_id: str | None,
) -> None:
    """Execute a database-authorized Team claim and conditionally publish its terminal result.

    The claim token, not the Celery message, owns result publication. No database transaction is
    held while downloading artifacts or running a domain service.
    """
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in the Team environment
        raise RuntimeError("team worker requires psycopg") from exc

    (
        job_id, workspace_id, project_id, attempt_id, execution_token, _queue_name,
        _resource_class, _task_schema_version, request_hash,
    ) = claim
    with psycopg.connect(database_url) as connection:
        _set_scope(connection, str(workspace_id), str(project_id or ""))
        row = connection.execute(
            """SELECT j.job_json,a.attempt_json,a.execution_token_hash,r.request_json
               FROM cra_control.jobs j
               JOIN cra_control.job_attempts a ON a.job_id=j.job_id
               JOIN cra_control.job_requests r ON r.job_id=j.job_id
               WHERE j.job_id=%s AND a.attempt_id=%s""",
            (job_id, attempt_id),
        ).fetchone()
        if not row:
            raise RuntimeError("claimed_job_not_visible_under_rls")
        job = JobRecord.model_validate(row[0])
        attempt = JobAttempt.model_validate(row[1])
        if not _token_matches(str(execution_token), str(row[2])):
            raise RuntimeError("stale_execution_token")
        if job.request_hash != str(request_hash):
            raise RuntimeError("job_request_hash_mismatch")
        request = row[3]
        if not isinstance(request, dict):
            raise RuntimeError("job_request_invalid")
        now = datetime.now(UTC)
        running_attempt = attempt.model_copy(update={
            "status": AttemptStatus.RUNNING,
            "worker_id_hash": worker_id_hash,
            "celery_task_id": celery_task_id,
            "started_at": attempt.started_at or now,
            "heartbeat_at": now,
            "updated_at": now,
        })
        running_job = job.model_copy(update={
            "status": JobStatus.RUNNING,
            "started_at": job.started_at or now,
            "heartbeat_at": now,
            "updated_at": now,
            "revision": job.revision + 1,
        })
        connection.execute(
            """UPDATE cra_control.job_attempts SET status='running',attempt_json=%s::jsonb
               WHERE attempt_id=%s AND execution_token_hash=%s""",
            (running_attempt.model_dump_json(), attempt_id, stable_hash(str(execution_token))),
        )
        connection.execute(
            "UPDATE cra_control.jobs SET status='running',job_json=%s::jsonb,updated_at=%s WHERE job_id=%s",
            (running_job.model_dump_json(), now, job_id),
        )
        connection.commit()

    result_refs: list[str] = []
    terminal_attempt = AttemptStatus.SUCCEEDED
    error_code: str | None = None
    try:
        result_refs = _dispatch(job=running_job, request=request, database_url=database_url)
    except Exception as exc:
        terminal_attempt = AttemptStatus.FAILED_TERMINAL
        error_code = _safe_error_code(exc)
    _finalize(
        database_url=database_url,
        workspace_id=str(workspace_id),
        project_id=str(project_id or ""),
        job_id=str(job_id),
        attempt_id=str(attempt_id),
        execution_token=str(execution_token),
        terminal_attempt=terminal_attempt,
        error_code=error_code,
        result_refs=result_refs,
    )


def _dispatch(*, job: JobRecord, request: dict, database_url: str) -> list[str]:
    if job.job_type in {"analysis", "indexing"}:
        return _execute_analysis(job, request, database_url=database_url)
    if job.job_type == "maintenance":
        return []
    raise RuntimeError(f"team_{job.job_type}_handler_unavailable")


def _execute_analysis(job: JobRecord, request: dict, *, database_url: str) -> list[str]:
    settings = PlatformSettings.from_env()
    artifacts = S3ArtifactStore(
        settings.s3_endpoint_url or "", settings.s3_bucket or "",
        access_key=os.getenv("AWS_ACCESS_KEY_ID"), secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    payload = AnalysisJobPayload.model_validate(request)
    with tempfile.TemporaryDirectory(prefix=f"cra-{job.job_type}-") as directory:
        root = Path(directory)
        repository = root / "repository.zip"
        with artifacts.open(payload.repository_storage_key) as source, repository.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        validate_archive(repository)
        paper: Path | None = None
        if payload.paper_storage_key:
            paper = root / "paper.pdf"
            with artifacts.open(payload.paper_storage_key) as source, paper.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            validate_pdf_header(paper)
        output = root / "output"
        state = run_analysis(
            repository, output, None, paper,
            text_llm_enabled=payload.text_llm_enabled,
            vision_vlm_enabled=payload.vision_vlm_enabled,
            external_text_consent=payload.external_text_consent,
            external_vision_consent=payload.external_vision_consent,
            task_id=job.domain_run_id,
            structured_index_enabled=True,
            repository_key=payload.repository_key,
        )
        result_dir = Path(str(state.get("output_dir") or ""))
        if not result_dir.is_dir():
            raise RuntimeError("analysis_result_missing")
        archive_path = root / "result.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(result_dir.rglob("*")):
                if path.is_symlink():
                    raise RuntimeError("analysis_result_symlink_rejected")
                if path.is_file():
                    archive.write(path, path.relative_to(result_dir).as_posix())
        return [_publish_s3_result(
            job, archive_path, artifacts, database_url=database_url,
            kind="report" if job.job_type == "analysis" else "export",
        )]


def _publish_s3_result(
    job: JobRecord,
    path: Path,
    artifacts: S3ArtifactStore,
    *,
    database_url: str,
    kind: str,
) -> str:
    artifact_id = f"artifact_{uuid4().hex}"
    with path.open("rb") as source:
        staging_key, digest, size = artifacts.stage(artifact_id, source)
    storage_key = (
        f"{job.workspace_id}/{job.project_id or 'shared'}/generated/{artifact_id}.zip"
    )
    artifacts.finalize(staging_key, storage_key, digest)
    now = datetime.now(UTC)
    record = ArtifactRecord(
        artifact_id=artifact_id,
        workspace_id=job.workspace_id,
        project_id=job.project_id or "",
        kind=kind,
        status="available",
        storage_key=storage_key,
        content_hash=digest,
        size_bytes=size,
        media_type="application/zip",
        created_at=now,
        updated_at=now,
    )
    import psycopg
    with psycopg.connect(database_url) as connection:
        _set_scope(connection, job.workspace_id, job.project_id or "")
        connection.execute(
            """INSERT INTO cra_control.artifacts(
                 artifact_id,workspace_id,project_id,status,storage_key,content_hash,
                 artifact_json,created_at,updated_at
               ) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
            (
                artifact_id, job.workspace_id, job.project_id, record.status, storage_key,
                digest, record.model_dump_json(), now, now,
            ),
        )
        connection.commit()
    return artifact_id


def _finalize(
    *,
    database_url: str,
    workspace_id: str,
    project_id: str,
    job_id: str,
    attempt_id: str,
    execution_token: str,
    terminal_attempt: AttemptStatus,
    error_code: str | None,
    result_refs: list[str],
) -> None:
    import psycopg
    with psycopg.connect(database_url) as connection:
        _set_scope(connection, workspace_id, project_id)
        row = connection.execute(
            """SELECT j.job_json,a.attempt_json,a.execution_token_hash
               FROM cra_control.jobs j JOIN cra_control.job_attempts a ON a.job_id=j.job_id
               WHERE j.job_id=%s AND a.attempt_id=%s FOR UPDATE""",
            (job_id, attempt_id),
        ).fetchone()
        if not row or not _token_matches(execution_token, str(row[2])):
            return
        job = JobRecord.model_validate(row[0])
        attempt = JobAttempt.model_validate(row[1])
        if job.current_attempt_number != attempt.attempt_number:
            return
        now = datetime.now(UTC)
        if job.cancel_requested or job.status is JobStatus.CANCELLING:
            terminal_attempt = AttemptStatus.CANCELLED
            terminal_job = JobStatus.CANCELLED
            error_code = "job_cancelled"
        elif terminal_attempt is AttemptStatus.SUCCEEDED:
            terminal_job = JobStatus.COMPLETED
        else:
            terminal_job = JobStatus.FAILED
        finished_attempt = attempt.model_copy(update={
            "status": terminal_attempt,
            "finished_at": now,
            "updated_at": now,
            "error_code": error_code,
            "retryable": False,
        })
        finished_job = job.model_copy(update={
            "status": terminal_job,
            "finished_at": now,
            "updated_at": now,
            "error_code": error_code,
            "result_artifact_ref_ids": result_refs,
            "revision": job.revision + 1,
        })
        connection.execute(
            """UPDATE cra_control.job_attempts SET status=%s,attempt_json=%s::jsonb
               WHERE attempt_id=%s AND execution_token_hash=%s""",
            (
                terminal_attempt, finished_attempt.model_dump_json(), attempt_id,
                stable_hash(execution_token),
            ),
        )
        connection.execute(
            "UPDATE cra_control.jobs SET status=%s,job_json=%s::jsonb,updated_at=%s WHERE job_id=%s",
            (terminal_job, finished_job.model_dump_json(), now, job_id),
        )
        connection.commit()


def _set_scope(connection, workspace_id: str, project_id: str) -> None:
    connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))
    connection.execute("SELECT set_config('app.project_id',%s,true)", (project_id,))


def _token_matches(raw: str, expected_hash: str) -> bool:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() == expected_hash


def _safe_error_code(exc: Exception) -> str:
    value = str(exc)
    if value.startswith("team_") and value.endswith("_handler_unavailable"):
        return value
    return "job_execution_failed"
