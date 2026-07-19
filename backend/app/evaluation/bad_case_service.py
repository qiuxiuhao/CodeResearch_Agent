from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import (
    BadCase,
    BadCaseEvent,
    BadCaseTransitionRequest,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id
from backend.app.evaluation.store_protocol import EvaluationStoreError, EvaluationStoreProtocol


ALLOWED_TRANSITIONS = {
    "open": {"triaged", "rejected"},
    "triaged": {"confirmed", "rejected"},
    "confirmed": {"fixing", "rejected"},
    "fixing": {"fixed", "rejected"},
    "fixed": {"verified"},
    "verified": {"closed"},
    "closed": {"open"},
    "rejected": set(),
}


class BadCaseService:
    def __init__(self, store: EvaluationStoreProtocol) -> None:
        self.store = store

    def transition(
        self,
        bad_case_id: str,
        target_status: str,
        request: BadCaseTransitionRequest,
        *,
        actor_scope: str,
    ) -> BadCase:
        current = self.store.get_bad_case(bad_case_id)
        if current.revision != request.based_on_revision:
            raise EvaluationStoreError("bad_case_conflict", bad_case_id)
        if target_status not in ALLOWED_TRANSITIONS.get(current.status, set()):
            raise EvaluationStoreError("bad_case_transition_invalid", f"{current.status}->{target_status}")
        root_cause = request.confirmed_root_cause or current.confirmed_root_cause
        fix_reference = request.fix_reference or current.fix_reference
        verification_id = current.verification_id
        if target_status == "confirmed" and root_cause is None:
            raise EvaluationStoreError("bad_case_root_cause_required")
        if target_status == "fixed" and fix_reference is None:
            raise EvaluationStoreError("fix_reference_required")
        if target_status == "verified":
            verification = request.verification
            if verification is None or verification.bad_case_id != bad_case_id:
                raise EvaluationStoreError("bad_case_verification_required")
            if not (
                verification.case_passed
                and verification.regression_case_passed
                and verification.relevant_rules_passed
            ):
                raise EvaluationStoreError("bad_case_verification_failed")
            results = self.store.list_case_results(verification.verification_run_id)
            result = next(
                (
                    item for item in results
                    if item.result_id == verification.verification_case_result_id
                ),
                None,
            )
            if result is None or result.evaluation_outcome != "passed" or not result.complete:
                raise EvaluationStoreError("bad_case_verification_result_invalid")
            promotions = self.store.list_promotions(bad_case_id)
            if not any(
                item.reproduction_status == "reproduced" and item.new_case_id == result.case_id
                for item in promotions
            ):
                raise EvaluationStoreError("bad_case_regression_case_mismatch")
            if not verification.required_gate_rule_ids:
                raise EvaluationStoreError("bad_case_relevant_hard_rules_required")
            self.store.save_bad_case_verification(verification)
            verification_id = verification.verification_id
        if target_status == "closed" and not (root_cause and fix_reference and verification_id):
            raise EvaluationStoreError("bad_case_close_requirements_missing")
        now = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "status": target_status,
                "revision": current.revision + 1,
                "confirmed_root_cause": root_cause,
                "fix_reference": fix_reference,
                "verification_id": verification_id,
                "evidence_ref_ids": sorted(set(current.evidence_ref_ids + request.artifact_ref_ids)),
                "updated_at": now,
            }
        )
        event = BadCaseEvent(
            event_id=stable_id("bad_case_event", [bad_case_id, updated.revision]),
            bad_case_id=bad_case_id,
            sequence=updated.revision,
            from_status=current.status,
            to_status=target_status,
            actor_scope_hash=stable_hash(actor_scope),
            based_on_revision=request.based_on_revision,
            reason_code=request.reason_code,
            artifact_ref_ids=request.artifact_ref_ids,
            created_at=now,
        )
        self.store.append_bad_case_event(event)
        self.store.save_bad_case(updated)
        return updated
