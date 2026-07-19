from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.config.application import ApplicationConfig
from backend.app.control_plane.access import (
    AccessContext, AccessDeniedError, DefaultAccessPolicy, permission_for_job_type,
)
from backend.app.control_plane.artifacts import LocalArtifactStore
from backend.app.control_plane.config import PlatformSettings
from backend.app.control_plane.domain_handlers import (
    LocalArtifactResolver, build_backup_handler, build_maintenance_handler,
)
from backend.app.control_plane.jobs import (
    InProcessJobBackend, JobExecutionContext, JobRequest, classify_job_error,
)
from backend.app.control_plane.runtime import ControlPlaneRuntime
from backend.app.control_plane.schemas import (
    ArtifactExecutionRef, ArtifactRecord, AttemptStatus, JobStatus,
)
from backend.app.control_plane.store import ControlPlaneError, LocalControlPlaneStore
from backend.app.main import app


def test_sensitive_job_types_have_dedicated_permissions():
    assert permission_for_job_type("backup") == "backup.manage"
    assert permission_for_job_type("restore") == "restore.manage"
    assert permission_for_job_type("maintenance") == "maintenance.manage"
    assert permission_for_job_type("analysis") == "job.create"
    policy = DefaultAccessPolicy()
    editor = AccessContext(
        actor_id="user", workspace_id="w", project_id="p",
        workspace_role="member", project_role="editor",
    )
    with pytest.raises(AccessDeniedError):
        policy.require(editor, "backup.manage")
    granted = AccessContext(
        actor_id="user", workspace_id="w", project_id="p",
        workspace_role="member", project_role="editor",
        explicit_permissions=frozenset({"backup.manage"}),
    )
    policy.require(granted, "backup.manage")


def test_internal_backup_catalog_is_workspace_and_project_scoped(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    own = _available_artifact(store, artifacts, "own", "w", "p", b"own")
    _available_artifact(store, artifacts, "foreign", "other", "p", b"foreign")

    async def run():
        backend = InProcessJobBackend(store, {"backup": build_backup_handler(store, artifacts)})
        handle = await backend.submit(_request("backup", {"label": "scope"}))
        await backend.shutdown()
        return store.get_job(handle.job_id)

    job = asyncio.run(run())
    backup = store.get_artifact(job.result_artifact_ref_ids[0])
    with zipfile.ZipFile(artifacts.path_for_read(backup.storage_key)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        names = archive.namelist()
    assert manifest["workspace_id"] == "w" and manifest["project_id"] == "p"
    assert [item["artifact_id"] for item in manifest["artifact_catalog"]] == [own.artifact_id]
    assert not any("foreign" in name for name in names)


def test_maintenance_never_scans_foreign_or_unknown_staging_files(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    own = _staging_artifact(store, artifacts, "own", "w", "p")
    foreign = _staging_artifact(store, artifacts, "foreign", "other", "p")
    unknown = artifacts.staging_root / "unknown"
    unknown.write_bytes(b"unknown")

    async def run():
        backend = InProcessJobBackend(
            store, {"maintenance": build_maintenance_handler(store, artifacts)},
        )
        await backend.submit(_request(
            "maintenance", {"action": "cleanup_staging", "older_than_seconds": 3600},
        ))
        await backend.shutdown()

    asyncio.run(run())
    assert not (artifacts.root / own.storage_key).exists()
    assert (artifacts.root / foreign.storage_key).exists()
    assert unknown.exists()


def test_restart_recovery_supersedes_old_attempt_and_blocks_late_result(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    created = store.create_job(
        workspace_id="w", project_id="p", job_type="analysis", queue_name="cra.analysis",
        request={"value": 1}, idempotency_key="restart-case", actor_id_hash="actor",
    )
    store.transition_job(created.job.job_id, JobStatus.DISPATCHING)
    store.transition_job(created.job.job_id, JobStatus.DISPATCHED)
    store.transition_attempt(created.attempt.attempt_id, created.execution_token, AttemptStatus.DISPATCHED)
    store.transition_attempt(created.attempt.attempt_id, created.execution_token, AttemptStatus.CLAIMED)
    store.transition_attempt(created.attempt.attempt_id, created.execution_token, AttemptStatus.RUNNING)
    store.transition_job(created.job.job_id, JobStatus.RUNNING)
    recovered = store.recover_incomplete_jobs()
    assert len(recovered) == 1
    assert store.get_attempt(created.attempt.attempt_id).status is AttemptStatus.LOST
    assert recovered[0].attempt.attempt_number == 2
    with pytest.raises(ControlPlaneError, match="late_attempt_result"):
        store.complete_attempt(
            created.attempt.attempt_id, created.execution_token, AttemptStatus.SUCCEEDED,
        )


def test_shutdown_is_bounded_and_persists_unfinished_attempt(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    blocker = asyncio.Event()

    async def handler(_context, _payload):
        await blocker.wait()
        return []

    async def run():
        backend = InProcessJobBackend(store, {"analysis": handler})
        handle = await backend.submit(_request("analysis", {}))
        await asyncio.sleep(0.01)
        started = time.monotonic()
        await backend.shutdown(grace_seconds=0.02)
        return handle, time.monotonic() - started

    handle, duration = asyncio.run(run())
    assert duration < 1.2
    assert store.get_job(handle.job_id).status is JobStatus.RETRY_WAIT
    assert store.get_attempt(handle.attempt_id).status is AttemptStatus.LOST


def test_long_attempt_heartbeat_advances_without_handler_polling(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")

    async def handler(_context, _payload):
        await asyncio.sleep(0.18)
        return []

    async def run():
        backend = InProcessJobBackend(
            store, {"analysis": handler}, heartbeat_interval_seconds=0.05,
        )
        handle = await backend.submit(_request("analysis", {}))
        await asyncio.sleep(0.08)
        heartbeat = store.get_attempt(handle.attempt_id).heartbeat_at
        await backend.shutdown()
        return handle, heartbeat

    handle, heartbeat = asyncio.run(run())
    assert heartbeat is not None
    assert store.get_job(handle.job_id).status is JobStatus.COMPLETED


def test_artifact_resolver_rechecks_scope_status_and_file_hash(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    record = _available_artifact(store, artifacts, "artifact", "w", "p", b"original")
    created = store.create_job(
        workspace_id="w", project_id="p", job_type="analysis", queue_name="cra.analysis",
        request={}, idempotency_key="resolver-case", actor_id_hash="actor",
    )
    store.transition_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.DISPATCHED,
    )
    store.transition_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.CLAIMED,
    )
    store.transition_attempt(
        created.attempt.attempt_id, created.execution_token, AttemptStatus.RUNNING,
    )
    context = JobExecutionContext(store, created)
    reference = ArtifactExecutionRef(
        artifact_id=record.artifact_id,
        expected_content_hash=record.content_hash,
        expected_kind=record.kind,
    )
    LocalArtifactResolver(store, artifacts).verify(context, reference)
    artifacts.path_for_read(record.storage_key).write_bytes(b"tampered")
    with pytest.raises(ControlPlaneError, match="artifact_hash_mismatch"):
        LocalArtifactResolver(store, artifacts).verify(context, reference)


def test_explicit_yaml_paths_are_cwd_independent_and_ignore_legacy_override(
    monkeypatch, tmp_path,
):
    config_root = tmp_path / "config"
    config_root.mkdir()
    config_path = config_root / "local.yaml"
    config_path.write_text(
        "schema_version: '2.0'\nprofile: local\n"
        "database:\n  control_url: sqlite:///../state/control.sqlite3\n"
        "artifacts:\n  local_root: ../state/artifacts\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CRA_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CONTROL_DATABASE_URL", "sqlite:///wrong.sqlite3")
    first = PlatformSettings.from_env()
    monkeypatch.chdir(tmp_path)
    second = PlatformSettings.from_env()
    expected = (tmp_path / "state" / "control.sqlite3").resolve()
    assert first.control_database_url == second.control_database_url == f"sqlite:///{expected}"
    assert first.artifact_root == second.artifact_root == (tmp_path / "state" / "artifacts").resolve()


def test_explicit_v2_local_config_disables_legacy_scheduling(monkeypatch, tmp_path):
    config_path = tmp_path / "local.yaml"
    config_path.write_text(
        "schema_version: '2.0'\nprofile: local\n"
        f"database:\n  control_url: sqlite:///{tmp_path / 'control.sqlite3'}\n"
        f"artifacts:\n  local_root: {tmp_path / 'artifacts'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CRA_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("CRA_LEGACY_INTERNAL_API_ENABLED", "false")
    with TestClient(app) as client:
        response = client.post("/analysis/tasks", json={"zip_path": "fixture.zip"})
        paths = client.get("/openapi.json").json()["paths"]
    assert response.status_code == 410
    assert response.json()["detail"]["error_code"] == "legacy_api_disabled"
    assert "/analysis/tasks" not in paths


def test_local_runtime_lock_rejects_second_owner(tmp_path):
    settings = PlatformSettings(
        control_database_url=f"sqlite:///{tmp_path / 'control.sqlite3'}",
        observability_database_url=f"sqlite:///{tmp_path / 'observability.sqlite3'}",
        checkpoint_database_url=f"sqlite:///{tmp_path / 'checkpoints.sqlite3'}",
        artifact_root=tmp_path / "artifacts",
    )

    async def run():
        first = ControlPlaneRuntime.build(settings)
        await first.start()
        try:
            with pytest.raises(ControlPlaneError, match="local_runtime_already_running"):
                ControlPlaneRuntime.build(settings)
        finally:
            await first.shutdown()

    asyncio.run(run())


def test_error_classifier_preserves_stable_codes_without_raw_message():
    assert classify_job_error(ControlPlaneError("artifact_hash_mismatch")) == (
        AttemptStatus.FAILED_TERMINAL, "artifact_hash_mismatch",
    )
    assert classify_job_error(RuntimeError("secret path /private/user")) == (
        AttemptStatus.FAILED_TERMINAL, "job_internal_error",
    )


def _request(job_type, payload):
    return JobRequest(
        workspace_id="w", project_id="p", job_type=job_type,
        queue_name=f"cra.{job_type}", payload=payload,
        idempotency_key=f"stability-{job_type}-{time.monotonic_ns()}", actor_id_hash="actor",
    )


def _staging_artifact(store, artifacts, artifact_id, workspace_id, project_id):
    key, digest, size = artifacts.stage(artifact_id, io.BytesIO(artifact_id.encode()))
    old = datetime.now(UTC) - timedelta(days=2)
    record = ArtifactRecord(
        artifact_id=artifact_id, workspace_id=workspace_id, project_id=project_id,
        kind="fixture", status="staging", storage_key=key, content_hash=digest,
        size_bytes=size, media_type="application/octet-stream", created_at=old, updated_at=old,
    )
    store.save_artifact(record)
    return record


def _available_artifact(store, artifacts, artifact_id, workspace_id, project_id, content):
    key, digest, size = artifacts.stage(artifact_id, io.BytesIO(content))
    now = datetime.now(UTC)
    record = ArtifactRecord(
        artifact_id=artifact_id, workspace_id=workspace_id, project_id=project_id,
        kind="fixture", status="staging", storage_key=key, content_hash=digest,
        size_bytes=size, media_type="application/octet-stream", created_at=now, updated_at=now,
    )
    store.save_artifact(record)
    for status in ("quarantined", "validating"):
        record = record.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})
        store.save_artifact(record)
    final_key = f"{workspace_id}/{project_id}/{artifact_id}.bin"
    artifacts.finalize(key, final_key, digest)
    record = record.model_copy(update={
        "status": "available", "storage_key": final_key, "updated_at": datetime.now(UTC),
    })
    store.save_artifact(record)
    return record
