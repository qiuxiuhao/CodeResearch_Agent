from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import EvaluationSubject
from backend.app.evaluation.stable_ids import stable_hash, stable_id


class EvaluationSubjectError(ValueError):
    pass


def build_evaluation_subject(
    *,
    subject_type: str,
    code_commit_sha: str,
    code_tag: str | None,
    worktree_patch_hash: str | None,
    config_hash: str,
    prompt_profile_ids: dict[str, str] | None = None,
    model_profile_ids: dict[str, str] | None = None,
    provider_revisions: dict[str, str] | None = None,
    dependency_lock_hash: str,
    created_at: datetime | None = None,
) -> EvaluationSubject:
    payload = {
        "subject_type": subject_type,
        "code_commit_sha": code_commit_sha,
        "code_tag": code_tag,
        "worktree_patch_hash": worktree_patch_hash,
        "config_hash": config_hash,
        "prompt_profile_ids": prompt_profile_ids or {},
        "model_profile_ids": model_profile_ids or {},
        "provider_revisions": provider_revisions or {},
        "dependency_lock_hash": dependency_lock_hash,
    }
    subject_hash = stable_hash(payload)
    return EvaluationSubject(
        subject_id=stable_id("subject", payload),
        subject_hash=subject_hash,
        created_at=created_at or datetime.now(UTC),
        **payload,
    )


def require_formal_baseline_subject(subject: EvaluationSubject) -> None:
    validate_subject_hash(subject)
    if not subject.formal_baseline_eligible:
        raise EvaluationSubjectError("formal_baseline_requires_clean_commit_subject")


def validate_subject_hash(subject: EvaluationSubject) -> None:
    expected = stable_hash(
        {
            "subject_type": subject.subject_type,
            "code_commit_sha": subject.code_commit_sha,
            "code_tag": subject.code_tag,
            "worktree_patch_hash": subject.worktree_patch_hash,
            "config_hash": subject.config_hash,
            "prompt_profile_ids": subject.prompt_profile_ids,
            "model_profile_ids": subject.model_profile_ids,
            "provider_revisions": subject.provider_revisions,
            "dependency_lock_hash": subject.dependency_lock_hash,
        }
    )
    if expected != subject.subject_hash:
        raise EvaluationSubjectError("evaluation_subject_hash_mismatch")
