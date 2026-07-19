from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from pydantic import Field

from .schemas import StrictModel


ResourceStatus = Literal[
    "active", "archived", "deletion_requested", "deleting", "deleted", "deletion_failed",
]


class ResourceLifecycle(StrictModel):
    schema_version: str = "2.0"
    resource_type: Literal["workspace", "project"]
    resource_id: str
    workspace_id: str
    status: ResourceStatus = "active"
    legal_hold: bool = False
    revision: int = Field(default=1, ge=1)


class RetentionPolicy(StrictModel):
    schema_version: str = "2.0"
    soft_delete_grace_days: int = 30
    job_event_days: int = 180
    audit_days: int = 365
    trace_metadata_days: int = 14
    diagnostic_trace_days: int = 7
    terminal_checkpoint_days: int = 30
    rejected_staging_hours: int = 24
    orphan_artifact_days: int = 7
    daily_backup_days: int = 30
    weekly_backup_weeks: int = 12
    monthly_backup_months: int = 12


@dataclass(frozen=True, slots=True)
class DeletionPreconditions:
    active_job_ids: tuple[str, ...] = ()
    protected_reference_ids: tuple[str, ...] = ()
    legal_hold: bool = False


class DeletionBlockedError(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__(",".join(reasons))
        self.reasons = reasons


def request_deletion(
    resource: ResourceLifecycle, preconditions: DeletionPreconditions,
) -> ResourceLifecycle:
    reasons = []
    if resource.status not in {"active", "archived", "deletion_failed"}:
        reasons.append("invalid_resource_status")
    if resource.legal_hold or preconditions.legal_hold:
        reasons.append("legal_hold")
    if preconditions.protected_reference_ids:
        reasons.append("protected_reference")
    if reasons:
        raise DeletionBlockedError(reasons)
    # Active jobs are cancelled by the Delete Job and therefore do not permit physical deletion,
    # but they do permit the soft-deletion request that blocks new work.
    return resource.model_copy(update={
        "status": "deletion_requested", "revision": resource.revision + 1,
    })


def begin_physical_deletion(
    resource: ResourceLifecycle, preconditions: DeletionPreconditions,
) -> ResourceLifecycle:
    if resource.status != "deletion_requested":
        raise DeletionBlockedError(["deletion_not_requested"])
    reasons = []
    if preconditions.active_job_ids:
        reasons.append("active_jobs")
    if preconditions.protected_reference_ids:
        reasons.append("protected_reference")
    if resource.legal_hold or preconditions.legal_hold:
        reasons.append("legal_hold")
    if reasons:
        raise DeletionBlockedError(reasons)
    return resource.model_copy(update={"status": "deleting", "revision": resource.revision + 1})
