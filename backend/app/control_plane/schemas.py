from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


SCHEMA_VERSION = "2.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "created_at", "updated_at", "scheduled_at", "started_at", "heartbeat_at",
        "finished_at", "lease_until", "next_retry_at", "occurred_at", "expires_at",
        "used_at", "revoked_at", "validated_at", check_fields=False,
    )
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class JobStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD = "dead"


class AttemptStatus(StrEnum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"
    LOST = "lost"
    SUPERSEDED = "superseded"


JobType = Literal[
    "analysis", "indexing", "research", "alignment", "evaluation", "replay",
    "export", "backup", "restore", "maintenance", "delete",
]


class JobRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    job_id: str = Field(min_length=1, max_length=128)
    workspace_id: str
    project_id: str | None = None
    job_type: JobType
    queue_name: str = Field(min_length=1, max_length=128)
    resource_class: Literal["cpu", "io", "provider", "gpu"] = "cpu"
    priority: int = Field(default=0, ge=-100, le=100)
    domain_run_id: str | None = None
    retry_of_job_id: str | None = None
    status: JobStatus = JobStatus.QUEUED
    dispatch_block_reason: str | None = None
    current_attempt_number: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=100)
    idempotency_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_schema_version: int = Field(default=1, ge=1)
    handler_version: str = "1"
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested: bool = False
    retryable: bool = False
    error_code: str | None = None
    result_artifact_ref_ids: list[str] = Field(default_factory=list, max_length=200)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def terminal_finished_at(self) -> "JobRecord":
        terminal = {
            JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.DEAD,
        }
        if (self.status in terminal) != (self.finished_at is not None):
            raise ValueError("finished_at must be set exactly for terminal Job states")
        return self


class JobAttempt(StrictModel):
    schema_version: str = SCHEMA_VERSION
    attempt_id: str
    job_id: str
    attempt_number: int = Field(ge=1)
    status: AttemptStatus = AttemptStatus.CREATED
    execution_token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    celery_task_id: str | None = None
    worker_id_hash: str | None = None
    lease_until: datetime | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    retryable: bool = False
    created_at: datetime
    updated_at: datetime


class OutboxEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    outbox_event_id: str
    aggregate_type: Literal["job"] = "job"
    aggregate_id: str
    job_id: str
    attempt_id: str
    attempt_number: int = Field(ge=1)
    event_type: Literal["job.dispatch"] = "job.dispatch"
    task_schema_version: int = Field(ge=1)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    message_deduplication_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending", "publishing", "published", "failed"] = "pending"
    claim_token_hash: str | None = None
    lease_owner_hash: str | None = None
    lease_until: datetime | None = None
    publish_attempt: int = Field(default=0, ge=0)
    last_publish_error_code: str | None = None
    published_message_id: str | None = None
    next_retry_at: datetime | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class JobExecutionPolicy(StrictModel):
    schema_version: str = SCHEMA_VERSION
    job_type: JobType
    business_deadline_seconds: int = Field(gt=0)
    soft_time_limit_seconds: int = Field(gt=0)
    hard_time_limit_seconds: int = Field(gt=0)
    broker_visibility_timeout_seconds: int = Field(gt=0)
    heartbeat_interval_seconds: int = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    checkpoint_interval_seconds: int = Field(gt=0)
    max_stage_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_deadlines(self) -> "JobExecutionPolicy":
        values = (
            self.business_deadline_seconds, self.soft_time_limit_seconds,
            self.hard_time_limit_seconds, self.broker_visibility_timeout_seconds,
        )
        if list(values) != sorted(values) or len(set(values)) != 4:
            raise ValueError("deadline < soft limit < hard limit < visibility timeout is required")
        return self


WorkspaceRole = Literal["owner", "admin", "member", "viewer"]
ProjectRole = Literal["project_owner", "editor", "reviewer", "viewer"]


class WorkspaceMembership(StrictModel):
    schema_version: str = SCHEMA_VERSION
    workspace_id: str
    user_id: str
    role: WorkspaceRole
    status: Literal["active", "suspended", "revoked"] = "active"
    created_at: datetime
    updated_at: datetime


class ProjectMembership(StrictModel):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    workspace_id: str
    user_id: str
    role: ProjectRole
    status: Literal["active", "suspended", "revoked"] = "active"
    created_at: datetime
    updated_at: datetime


class ProjectAccessGrant(StrictModel):
    schema_version: str = SCHEMA_VERSION
    grant_id: str
    workspace_id: str
    project_id: str
    user_id: str
    permission: str
    created_at: datetime
    expires_at: datetime | None = None


class AuditEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    audit_event_id: str
    workspace_id: str | None = None
    project_id: str | None = None
    actor_id_hash: str
    action: str
    object_type: str
    object_id: str
    outcome: Literal["allowed", "denied", "succeeded", "failed"]
    reason_code: str
    occurred_at: datetime
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


ArtifactKind = Literal[
    "repository_zip", "git_repository", "paper_pdf", "report", "fixture", "export",
    "backup", "restore", "replay_manifest",
]


class ArtifactRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    artifact_id: str
    workspace_id: str
    project_id: str
    kind: ArtifactKind
    status: Literal[
        "staging", "quarantined", "validating", "available", "rejected",
        "orphaned", "deletion_requested", "deleted",
    ]
    storage_key: str = Field(pattern=r"^[a-zA-Z0-9/_\-.]+$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactExecutionRef(StrictModel):
    """Immutable artifact expectations captured when a Job is submitted."""

    artifact_id: str = Field(min_length=1, max_length=128)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_kind: ArtifactKind


class ProviderReservation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    reservation_id: str
    workspace_id: str
    project_id: str | None = None
    provider_profile_id: str
    model_id: str
    job_id: str
    attempt_id: str
    estimated_tokens: int = Field(ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    actual_tokens: int | None = Field(default=None, ge=0)
    actual_cost: float | None = Field(default=None, ge=0)
    lease_until: datetime
    status: Literal["reserved", "settled", "released", "expired"]
    created_at: datetime
    updated_at: datetime


class WorkerRegistration(StrictModel):
    schema_version: str = SCHEMA_VERSION
    worker_id_hash: str
    worker_version: str
    supported_job_types: list[JobType]
    min_task_schema_version: int = Field(ge=1)
    max_task_schema_version: int = Field(ge=1)
    min_database_schema_version: int = Field(ge=1)
    max_database_schema_version: int = Field(ge=1)
    handler_versions: dict[str, str]
    capabilities: list[str]
    queue_names: list[str]
    heartbeat_at: datetime


class BackupManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    backup_manifest_id: str
    application_version: str
    api_contract_version: str
    database_schema_version: str
    database_backup_id: str
    wal_position: str | None = None
    artifact_snapshot_id: str
    artifact_hash_catalog: str
    secret_backup_reference: str
    qdrant_rebuild_manifest: str
    created_at: datetime


class LocalToTeamMigration(StrictModel):
    schema_version: str = SCHEMA_VERSION
    migration_id: str
    status: Literal[
        "created", "scanning", "validating", "ready", "importing",
        "rebuilding_indexes", "verifying", "cutover_ready", "completed",
        "failed", "rolling_back", "rolled_back",
    ]
    dry_run: bool
    source_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_stages: list[str] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
