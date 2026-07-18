from __future__ import annotations

from typing import Protocol

from backend.app.observability.schemas import CallerIdentity, TraceFilter, TraceRecord


class ObservabilityAccessPolicy(Protocol):
    def can_list_traces(self, caller: CallerIdentity, filters: TraceFilter) -> bool: ...
    def can_read_trace(self, caller: CallerIdentity, trace: TraceRecord) -> bool: ...
    def can_read_diagnostic_metadata(self, caller: CallerIdentity, trace: TraceRecord) -> bool: ...


class LocalAdminAccessPolicy:
    """Conservative v1 policy: local admin or explicit repository membership."""

    def can_list_traces(self, caller: CallerIdentity, filters: TraceFilter) -> bool:
        if caller.identity_type == "local_admin":
            return True
        return bool(filters.repo_id and filters.repo_id in caller.repository_ids)

    def can_read_trace(self, caller: CallerIdentity, trace: TraceRecord) -> bool:
        if caller.identity_type == "local_admin":
            return True
        return bool(trace.repo_id and trace.repo_id in caller.repository_ids)

    def can_read_diagnostic_metadata(self, caller: CallerIdentity, trace: TraceRecord) -> bool:
        return caller.identity_type == "local_admin"
