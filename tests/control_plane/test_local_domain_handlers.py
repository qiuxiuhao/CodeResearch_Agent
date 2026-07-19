from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime

from backend.app.control_plane.artifacts import LocalArtifactStore
from backend.app.control_plane.domain_handlers import (
    build_backup_handler, build_delete_handler, build_export_handler, build_restore_handler,
)
from backend.app.control_plane.jobs import InProcessJobBackend, JobRequest
from backend.app.control_plane.schemas import ArtifactRecord, JobStatus
from backend.app.control_plane.store import LocalControlPlaneStore


def _available_artifact(store, artifacts, artifact_id="artifact_source"):
    staging, digest, size = artifacts.stage(artifact_id, io.BytesIO(b"fixture-content"))
    now = datetime.now(UTC)
    record = ArtifactRecord(
        artifact_id=artifact_id, workspace_id="w", project_id="p", kind="fixture",
        status="staging", storage_key=staging, content_hash=digest, size_bytes=size,
        media_type="application/octet-stream", created_at=now, updated_at=now,
    )
    store.save_artifact(record)
    record = record.model_copy(update={"status": "quarantined", "updated_at": datetime.now(UTC)})
    store.save_artifact(record)
    record = record.model_copy(update={"status": "validating", "updated_at": datetime.now(UTC)})
    store.save_artifact(record)
    artifacts.finalize(staging, f"w/p/{artifact_id}.bin", digest)
    record = record.model_copy(update={
        "status": "available", "storage_key": f"w/p/{artifact_id}.bin",
        "updated_at": datetime.now(UTC),
    })
    store.save_artifact(record)
    return record


def _request(job_type, payload, key):
    return JobRequest(
        workspace_id="w", project_id="p", job_type=job_type,
        queue_name=f"cra.{job_type}", payload=payload,
        idempotency_key=key, actor_id_hash="actor",
    )


def test_local_export_backup_restore_and_delete_handlers(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    source = _available_artifact(store, artifacts)

    async def run():
        backend = InProcessJobBackend(store)
        backend.register("export", build_export_handler(store, artifacts))
        backend.register("backup", build_backup_handler(store, artifacts))
        backend.register("restore", build_restore_handler(store, artifacts))
        backend.register("delete", build_delete_handler(store, artifacts))

        export = await backend.submit(_request(
            "export", {"artifact_ids": [source.artifact_id]}, "export-one",
        ))
        await backend.shutdown()
        export_job = store.get_job(export.job_id)
        export_record = store.get_artifact(export_job.result_artifact_ref_ids[0])

        backup = await backend.submit(_request("backup", {"label": "test"}, "backup-one"))
        await backend.shutdown()
        backup_job = store.get_job(backup.job_id)
        backup_record = store.get_artifact(backup_job.result_artifact_ref_ids[0])

        restore = await backend.submit(_request(
            "restore", {"backup_artifact_id": backup_record.artifact_id}, "restore-one",
        ))
        await backend.shutdown()
        restore_job = store.get_job(restore.job_id)

        delete = await backend.submit(_request(
            "delete", {"artifact_id": source.artifact_id}, "delete-one",
        ))
        await backend.shutdown()
        return export_job, export_record, backup_job, backup_record, restore_job, delete

    export_job, export_record, backup_job, backup_record, restore_job, delete = asyncio.run(run())
    assert export_job.status is JobStatus.COMPLETED
    assert export_record.kind == "export" and export_record.status == "available"
    assert backup_job.status is JobStatus.COMPLETED
    assert backup_record.kind == "backup" and backup_record.status == "available"
    assert restore_job.status is JobStatus.COMPLETED
    assert store.get_artifact(restore_job.result_artifact_ref_ids[0]).kind == "restore"
    assert store.get_job(delete.job_id).status is JobStatus.COMPLETED
    assert store.get_artifact(source.artifact_id).status == "deleted"
