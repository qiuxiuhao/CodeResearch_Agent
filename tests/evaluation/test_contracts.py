from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.evaluation.business_equivalence import compare_business_outputs
from backend.app.evaluation.schemas import (
    BusinessEquivalenceContract,
    EvaluationArtifactRef,
    EvaluationCase,
)
from backend.app.evaluation.stable_ids import stable_hash
from backend.app.evaluation.subjects import (
    EvaluationSubjectError,
    build_evaluation_subject,
    require_formal_baseline_subject,
)


COMMIT = "db6685a45baa5f75e4856cbc406e410ad313f332"


def _subject(**updates):
    values = {
        "subject_type": "code_commit",
        "code_commit_sha": COMMIT,
        "code_tag": "v1.8.0",
        "worktree_patch_hash": None,
        "config_hash": stable_hash("config"),
        "prompt_profile_ids": {"answer": "prompt-v1"},
        "model_profile_ids": {"text": "model-v1"},
        "provider_revisions": {},
        "dependency_lock_hash": stable_hash("lock"),
        "created_at": datetime.now(UTC),
    }
    values.update(updates)
    return build_evaluation_subject(**values)


def test_v1_8_tag_and_commit_are_recorded():
    subject = _subject()
    assert subject.code_commit_sha == COMMIT
    assert subject.code_tag == "v1.8.0"


def test_formal_baseline_subject_requires_clean_commit():
    require_formal_baseline_subject(_subject())
    patch = _subject(
        subject_type="worktree_patch",
        worktree_patch_hash="a" * 64,
        code_tag=None,
    )
    with pytest.raises(EvaluationSubjectError):
        require_formal_baseline_subject(patch)


def test_subject_hash_changes_when_config_changes():
    assert _subject().subject_hash != _subject(config_hash=stable_hash("config-v2")).subject_hash


def test_subject_hash_changes_when_prompt_profile_changes():
    changed = _subject(prompt_profile_ids={"answer": "prompt-v2"})
    assert _subject().subject_hash != changed.subject_hash


def test_worktree_subject_cannot_be_promoted_as_formal_baseline():
    with pytest.raises(EvaluationSubjectError):
        require_formal_baseline_subject(
            _subject(subject_type="worktree_patch", worktree_patch_hash="b" * 64, code_tag=None)
        )


def test_component_gold_discriminator():
    from backend.app.evaluation.mock_runner import build_synthetic_suite

    case = build_synthetic_suite().store.cases["synthetic-alignment-001"]
    restored = EvaluationCase.model_validate(case.model_dump(mode="json"))
    assert restored.gold.component == "alignment"
    assert restored.input.component == "alignment"


def test_synthetic_alignment_case_does_not_close_human_benchmark():
    from backend.app.evaluation.alignment_gold import audit_alignment_gold
    from backend.app.evaluation.mock_runner import build_synthetic_suite

    case = build_synthetic_suite().store.cases["synthetic-alignment-001"]
    audit = audit_alignment_gold([case], require_release_shape=True)
    assert audit.status == "ALIGNMENT_BENCHMARK_PENDING"
    assert "alignment_gold_not_human_authored" in audit.reason_codes


def test_artifact_resolver_rejects_arbitrary_path():
    with pytest.raises(ValidationError):
        EvaluationArtifactRef(
            artifact_ref_id="ref",
            artifact_type="fixture",
            artifact_id="fixture",
            content_hash="0" * 64,
            authority="business_fact",
            storage_kind="filesystem_fixture",
            storage_locator="/etc/passwd",
            media_type="text/plain",
            redaction_policy="metadata-only",
            availability_status="available",
        )


def test_telemetry_ids_are_ignored_in_business_equivalence():
    contract = BusinessEquivalenceContract(
        contract_id="retrieval-equivalence-v1",
        component="retrieval",
        required_equal_fields=["ranking", "status"],
        ignored_fields=["trace_id", "latency_ms"],
        normalizer_version="1",
        config_hash=stable_hash("equivalence-v1"),
    )
    left = {"ranking": ["a", "b"], "status": "ok", "trace_id": "one", "latency_ms": 1}
    right = {"ranking": ["a", "b"], "status": "ok", "trace_id": "two", "latency_ms": 9}
    assert compare_business_outputs(left, right, contract).equivalent


def test_retrieval_ranking_difference_breaks_equivalence():
    contract = BusinessEquivalenceContract(
        contract_id="retrieval-equivalence-v1",
        component="retrieval",
        required_equal_fields=["ranking"],
        normalizer_version="1",
        config_hash=stable_hash("equivalence-v1"),
    )
    assert not compare_business_outputs(
        {"ranking": ["a", "b"]}, {"ranking": ["b", "a"]}, contract
    ).equivalent


def test_float_tolerance_is_versioned():
    contract = BusinessEquivalenceContract(
        contract_id="float-v1",
        component="alignment",
        required_equal_fields=["score"],
        float_tolerances={"score": 0.01},
        normalizer_version="1",
        config_hash=stable_hash({"score": 0.01}),
    )
    assert compare_business_outputs({"score": 0.5}, {"score": 0.505}, contract).equivalent
