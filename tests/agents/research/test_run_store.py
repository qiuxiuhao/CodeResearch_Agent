from __future__ import annotations

import pytest

from backend.app.agents.research.planner import RuleBasedPlanner
from backend.app.agents.research.schemas import ResearchRunCreateRequest
from backend.app.persistence.research_run_store import ResearchRunStore, ResearchRunStoreError


def test_idempotency_is_scoped_and_request_hash_includes_repository(tmp_path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    request = ResearchRunCreateRequest(query="where")
    first, reused = store.create_run(
        repo_id="repo-a", index_version_id="v1", request=request,
        caller_scope="user-a", idempotency_key="same",
    )
    again, reused = store.create_run(
        repo_id="repo-a", index_version_id="v1", request=request,
        caller_scope="user-a", idempotency_key="same",
    )
    assert reused is True
    assert again["run_id"] == first["run_id"]
    with pytest.raises(ResearchRunStoreError) as caught:
        store.create_run(
            repo_id="repo-b", index_version_id="v1", request=request,
            caller_scope="user-a", idempotency_key="same",
        )
    assert caught.value.error_code == "idempotency_key_conflict"


def test_run_store_terminal_transition_is_atomic(tmp_path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    run, _ = store.create_run(
        repo_id="repo", index_version_id="v1",
        request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
    )
    store.update_status(run["run_id"], "completed", allowed_from=["queued"])
    with pytest.raises(ResearchRunStoreError, match="Terminal run"):
        store.update_status(run["run_id"], "running", allowed_from=["completed"])  # type: ignore[arg-type]


def test_plan_versions_are_persisted_idempotently(tmp_path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    run, _ = store.create_run(
        repo_id="repo", index_version_id="v1",
        request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
    )
    plan = RuleBasedPlanner().create_plan(query="x", query_type="symbol_lookup")
    store.save_plan(run["run_id"], plan, planner_request_hash="hash")
    store.save_plan(run["run_id"], plan, planner_request_hash="hash")
    versions = store.list_plan_versions(run["run_id"])
    assert len(versions) == 1
    assert versions[0]["status"] == "active"


def test_partial_is_terminal_and_cannot_resume(tmp_path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    run, _ = store.create_run(
        repo_id="repo", index_version_id="v1",
        request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
    )
    store.update_status(run["run_id"], "partial", allowed_from=["queued"])
    with pytest.raises(ResearchRunStoreError) as caught:
        store.mark_resumed(run["run_id"])
    assert caught.value.error_code == "resume_not_allowed"


def test_two_owners_cannot_hold_same_run_lease(tmp_path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    run, _ = store.create_run(
        repo_id="repo", index_version_id="v1",
        request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
    )
    assert store.acquire_lease(run["run_id"], "one") is not None
    assert store.acquire_lease(run["run_id"], "two") is None


def test_cancel_transitions_through_cancelling(tmp_path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    run, _ = store.create_run(
        repo_id="repo", index_version_id="v1",
        request=ResearchRunCreateRequest(query="x"), caller_scope="caller",
    )
    cancelling = store.request_cancel(run["run_id"])
    assert cancelling["status"] == "cancelling"
    cancelled = store.update_status(run["run_id"], "cancelled", allowed_from=["cancelling"])
    assert cancelled["status"] == "cancelled"
