from datetime import UTC, datetime
import json

import pytest

from backend.app.alignment.alignment_service import default_model_profile
from backend.app.alignment.schemas import (
    AlignmentDecision,
    AlignmentDecisionConfidence,
    AlignmentReviewRequest,
    PaperModuleProfile,
)
from backend.app.alignment.review_service import AlignmentReviewService
from backend.app.persistence.alignment_store import AlignmentStore, AlignmentStoreError


def _store(tmp_path):
    store = AlignmentStore(tmp_path / "alignment.sqlite3")
    store.save_model_profile(default_model_profile())
    return store


def _create(store, *, key=None, retry=None):
    profile = default_model_profile()
    return store.create_run(
        repo_id="repo", index_version_id="idx", paper_id="paper", input_hash="input",
        model_profile_id=profile.model_profile_id, request={"paper_id": "paper"},
        caller_scope="caller", idempotency_key=key, retry_of_run_id=retry,
    )[0]


def _profile(run_id):
    return PaperModuleProfile(
        profile_id="profile", alignment_run_id=run_id, repo_id="repo", index_version_id="idx",
        paper_id="paper", profile_type="module", granularity="contribution",
        source_group_key="group", canonical_name="Encoder", normalized_name="encoder",
        description="Encoder", content_hash="h", extractor_version="v1",
        profile_generation_version="v1", profile_quality=1.0,
    )


def _decision(run_id):
    return AlignmentDecision(
        decision_id="decision", alignment_run_id=run_id, profile_id="profile",
        decision_version="v1", status="abstained", selections=[], set_coverage=0,
        set_compatibility=1, confidence=AlignmentDecisionConfidence(has_implementation_probability=0),
        top_margin=0, decision_source="scorer", scorer_profile_id="scorer", created_at=datetime.now(UTC),
    )


def test_failed_run_can_retry_same_input(tmp_path):
    store = _store(tmp_path)
    first = _create(store)
    store.update_status(first["run_id"], "failed", allowed_from=["queued"])
    second = _create(store, retry=first["run_id"])
    assert second["attempt_number"] == 2
    assert second["retry_of_run_id"] == first["run_id"]


def test_successful_ready_run_is_reused(tmp_path):
    store = _store(tmp_path)
    run = _create(store)
    store.save_profiles(run["run_id"], [_profile(run["run_id"])])
    store.update_status(run["run_id"], "scoring", allowed_from=["queued"])
    store.save_decisions(run["run_id"], [_decision(run["run_id"])])
    store.mark_ready_and_activate(run["run_id"])
    reused, flag = store.create_run(
        repo_id="repo", index_version_id="idx", paper_id="paper", input_hash="input",
        model_profile_id=default_model_profile().model_profile_id, request={"paper_id": "paper"},
        caller_scope="caller-2",
    )
    assert flag is True
    assert reused["run_id"] == run["run_id"]


def test_two_coordinators_cannot_execute_same_alignment_run(tmp_path):
    store = _store(tmp_path)
    run = _create(store)
    assert store.acquire_lease(run["run_id"], "one") is not None
    assert store.acquire_lease(run["run_id"], "two") is None


def test_partial_stage_rows_not_visible_as_active(tmp_path):
    store = _store(tmp_path)
    run = _create(store)
    store.save_profiles(run["run_id"], [_profile(run["run_id"])])
    with pytest.raises(AlignmentStoreError, match="No alignment deployment"):
        store.get_deployment("repo", "idx", "paper")


def test_stage_manifest_keeps_completed_stage_history(tmp_path):
    store = _store(tmp_path)
    run = _create(store)
    store.save_profiles(run["run_id"], [_profile(run["run_id"])])
    store.update_status(run["run_id"], "scoring", allowed_from=["queued"])
    store.save_decisions(run["run_id"], [_decision(run["run_id"])])
    manifest = json.loads(store.get_run(run["run_id"])["stage_manifest_json"])
    assert manifest["profiling"]["count"] == 1
    assert manifest["scoring"]["decision_count"] == 1


def test_review_conflicts_on_stale_effective_revision(tmp_path):
    store = _store(tmp_path)
    run = _create(store)
    store.save_profiles(run["run_id"], [_profile(run["run_id"])])
    store.update_status(run["run_id"], "scoring", allowed_from=["queued"])
    store.save_decisions(run["run_id"], [_decision(run["run_id"])])
    service = AlignmentReviewService(store)
    service.add_review(
        "decision",
        AlignmentReviewRequest(action="add_note", note="checked", based_on_effective_revision=0),
        reviewer_scope="reviewer",
    )
    with pytest.raises(AlignmentStoreError, match="Effective revision is stale"):
        service.add_review(
            "decision",
            AlignmentReviewRequest(action="add_note", note="stale", based_on_effective_revision=0),
            reviewer_scope="reviewer",
        )
