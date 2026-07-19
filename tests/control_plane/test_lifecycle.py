from __future__ import annotations

import pytest

from backend.app.control_plane.lifecycle import (
    DeletionBlockedError, DeletionPreconditions, ResourceLifecycle,
    begin_physical_deletion, request_deletion,
)


def test_workspace_soft_delete_blocks_new_jobs():
    workspace = ResourceLifecycle(resource_type="workspace", resource_id="w", workspace_id="w")
    requested = request_deletion(workspace, DeletionPreconditions(active_job_ids=("j",)))
    assert requested.status == "deletion_requested"


def test_deletion_waits_for_running_jobs_safe_boundary():
    resource = ResourceLifecycle(
        resource_type="workspace", resource_id="w", workspace_id="w", status="deletion_requested",
    )
    with pytest.raises(DeletionBlockedError, match="active_jobs"):
        begin_physical_deletion(resource, DeletionPreconditions(active_job_ids=("j",)))


def test_frozen_gold_reference_blocks_physical_delete():
    workspace = ResourceLifecycle(resource_type="workspace", resource_id="w", workspace_id="w")
    with pytest.raises(DeletionBlockedError, match="protected_reference"):
        request_deletion(workspace, DeletionPreconditions(protected_reference_ids=("gold",)))


def test_legal_hold_blocks_deletion():
    workspace = ResourceLifecycle(
        resource_type="workspace", resource_id="w", workspace_id="w", legal_hold=True,
    )
    with pytest.raises(DeletionBlockedError, match="legal_hold"):
        request_deletion(workspace, DeletionPreconditions())
