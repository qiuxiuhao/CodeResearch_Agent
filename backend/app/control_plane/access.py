from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .schemas import ProjectRole, WorkspaceRole


SENSITIVE_PERMISSIONS = {
    "gold.read", "gold.freeze", "audit.read", "provider.manage",
    "trace.diagnostic", "backup.manage", "restore.manage", "maintenance.manage",
}

JOB_TYPE_PERMISSIONS: dict[str, str] = {
    "backup": "backup.manage",
    "restore": "restore.manage",
    "maintenance": "maintenance.manage",
}


def permission_for_job_type(job_type: str) -> str:
    """Return the permission checked before any job payload is inspected."""
    return JOB_TYPE_PERMISSIONS.get(job_type, "job.create")

WORKSPACE_PERMISSIONS: dict[WorkspaceRole, set[str]] = {
    "owner": {"*"},
    "admin": {
        "workspace.update", "member.manage", "project.manage", "artifact.read",
        "artifact.delete", "job.create", "job.cancel", "job.retry", "job.dead.manage",
        "alignment.review", "evaluation.run", "trace.read",
    },
    "member": set(),
    "viewer": set(),
}

PROJECT_PERMISSIONS: dict[ProjectRole, set[str]] = {
    "project_owner": {
        "project.update", "member.manage", "artifact.read", "artifact.create",
        "artifact.delete", "job.create", "job.cancel", "job.retry", "alignment.run",
        "alignment.review", "evaluation.run", "trace.read", "audit.project.read", "result.read",
    },
    "editor": {
        "artifact.read", "artifact.create", "job.create", "job.cancel", "job.retry",
        "alignment.run", "evaluation.run", "trace.read", "result.read",
    },
    "reviewer": {"artifact.read", "alignment.review", "gold.review", "trace.read", "result.read"},
    "viewer": {"artifact.read", "result.read", "trace.read"},
}


@dataclass(frozen=True, slots=True)
class AccessContext:
    actor_id: str
    workspace_id: str
    project_id: str | None
    workspace_role: WorkspaceRole
    project_role: ProjectRole | None = None
    explicit_permissions: frozenset[str] = frozenset()


class AccessPolicy(Protocol):
    def require(self, context: AccessContext, permission: str) -> None: ...


class AccessDeniedError(PermissionError):
    def __init__(self, permission: str) -> None:
        super().__init__("access_denied")
        self.permission = permission


class DefaultAccessPolicy:
    def require(self, context: AccessContext, permission: str) -> None:
        if permission in context.explicit_permissions:
            return
        workspace_permissions = WORKSPACE_PERMISSIONS[context.workspace_role]
        if "*" in workspace_permissions:
            return
        if permission in SENSITIVE_PERMISSIONS:
            raise AccessDeniedError(permission)
        if permission in workspace_permissions:
            return
        if context.project_id and context.project_role:
            if permission in PROJECT_PERMISSIONS[context.project_role]:
                return
        raise AccessDeniedError(permission)
