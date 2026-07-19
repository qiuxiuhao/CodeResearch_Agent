from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.control_plane.backup import RestoreInventory, RestoreVerificationError, verify_restore_inventory
from backend.app.control_plane.compatibility import worker_can_execute
from backend.app.control_plane.migration import MigrationItem, advance_migration, detect_id_collisions
from backend.app.control_plane.provider_reservations import ProviderReservationService
from backend.app.control_plane.schemas import (
    BackupManifest, JobRecord, JobStatus, LocalToTeamMigration, WorkerRegistration,
)
from backend.app.control_plane.store import LocalControlPlaneStore


def _job(now):
    return JobRecord(
        job_id="j", workspace_id="w", project_id="p", job_type="analysis",
        queue_name="cra.analysis", idempotency_key_hash="a" * 64,
        request_hash="b" * 64, task_schema_version=2, handler_version="3",
        created_at=now, updated_at=now,
    )


def _worker(now, task_min=1, task_max=2):
    return WorkerRegistration(
        worker_id_hash="worker", worker_version="2.0.0",
        supported_job_types=["analysis"], min_task_schema_version=task_min,
        max_task_schema_version=task_max, min_database_schema_version=1,
        max_database_schema_version=2, handler_versions={"analysis": "3"},
        capabilities=["cpu"], queue_names=["cra.analysis"], heartbeat_at=now,
    )


def test_dispatcher_routes_only_to_compatible_worker():
    now = datetime.now(UTC)
    assert worker_can_execute(_worker(now), _job(now), database_schema_version=2)
    assert not worker_can_execute(_worker(now, task_max=1), _job(now), database_schema_version=2)


def test_incompatible_task_waits_without_retry_storm():
    now = datetime.now(UTC)
    job = _job(now)
    assert not worker_can_execute(_worker(now, task_min=3, task_max=4), job, database_schema_version=2)
    assert job.status is JobStatus.QUEUED
    assert job.current_attempt_number == 1


def test_provider_reservation_recovers_after_worker_loss(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    service = ProviderReservationService(store)
    reservation = service.reserve(
        workspace_id="w", project_id="p", provider_profile_id="provider",
        model_id="model", job_id="j", attempt_id="a", estimated_tokens=100,
        estimated_cost=0.1, lease_seconds=1,
    )
    assert service.recover_expired(reservation.lease_until + timedelta(seconds=1)) == 1


def _manifest():
    return BackupManifest(
        backup_manifest_id="backup", application_version="2.0.0", api_contract_version="2",
        database_schema_version="1", database_backup_id="db", wal_position="0/1",
        artifact_snapshot_id="objects", artifact_hash_catalog="catalog",
        secret_backup_reference="secret", qdrant_rebuild_manifest="qdrant",
        created_at=datetime.now(UTC),
    )


def test_backup_manifest_links_database_and_artifact_snapshot():
    manifest = _manifest()
    verify_restore_inventory(manifest, RestoreInventory(
        database_backup_id="db", artifact_snapshot_id="objects",
        artifact_hash_catalog="catalog", available_secret_references=frozenset({"secret"}),
        database_schema_version="1",
    ))


def test_restore_fails_when_secret_key_is_missing():
    with pytest.raises(RestoreVerificationError, match="secret_backup_missing"):
        verify_restore_inventory(_manifest(), RestoreInventory(
            database_backup_id="db", artifact_snapshot_id="objects",
            artifact_hash_catalog="catalog", available_secret_references=frozenset(),
            database_schema_version="1",
        ))


def test_id_collision_is_detected_before_import():
    assert detect_id_collisions(
        [MigrationItem("workspace", "w", "one")],
        [MigrationItem("workspace", "w", "two")],
    ) == ["w"]


def test_migration_resumes_from_last_completed_stage():
    now = datetime.now(UTC)
    migration = LocalToTeamMigration(
        migration_id="m", status="created", dry_run=True,
        source_manifest_hash="a" * 64, created_at=now, updated_at=now,
    )
    scanning = advance_migration(migration, "scanning")
    assert scanning.completed_stages == ["created"]
    with pytest.raises(ValueError, match="invalid_migration_transition"):
        advance_migration(scanning, "importing")
