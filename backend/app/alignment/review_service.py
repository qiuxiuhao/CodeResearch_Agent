from __future__ import annotations

from datetime import UTC, datetime

from backend.app.alignment.schemas import (
    AlignmentDecision,
    AlignmentReview,
    AlignmentReviewRequest,
    AlignmentSelection,
    EffectiveAlignmentDecision,
)
from backend.app.alignment.stable_ids import review_id
from backend.app.persistence.alignment_store import AlignmentStore


class AlignmentReviewService:
    def __init__(self, store: AlignmentStore) -> None:
        self.store = store

    def add_review(
        self,
        decision_id: str,
        request: AlignmentReviewRequest,
        *,
        reviewer_scope: str,
    ) -> EffectiveAlignmentDecision:
        row = self.store.get_decision_row(decision_id)
        sequence = int(row["review_sequence"]) + 1
        payload = request.model_dump(mode="json")
        review = AlignmentReview(
            review_id=review_id(
                decision_id_value=decision_id,
                review_sequence=sequence,
                payload=payload,
            ),
            decision_id=decision_id,
            action=request.action,
            selections=request.selections,
            note=request.note,
            reviewer_scope_hash=review_id(
                decision_id_value="reviewer",
                review_sequence=1,
                payload=reviewer_scope,
            ),
            based_on_effective_revision=request.based_on_effective_revision,
            review_sequence=sequence,
            created_at=datetime.now(UTC),
        )
        self.store.add_review(review)
        return self.effective_decision(decision_id)

    def effective_decision(self, decision_id: str) -> EffectiveAlignmentDecision:
        row = self.store.get_decision_row(decision_id)
        base = AlignmentDecision.model_validate_json(row["decision_json"])
        reviews = self.store.list_reviews(decision_id)
        status = base.status
        selections = list(base.selections)
        for review in reviews:
            if review.action == "mark_no_implementation":
                status = "no_implementation"
                selections = []
            elif review.action == "reject":
                rejected = {item.candidate_id for item in review.selections}
                selections = [item for item in selections if item.candidate_id not in rejected]
                status = "accepted" if selections else "abstained"
            elif review.action in {"accept", "replace_candidate", "accept_multiple"}:
                selections = [
                    AlignmentSelection(
                        selection_id=f"review:{review.review_id}:{item.candidate_id}",
                        candidate_id=item.candidate_id,
                        relation_type=item.relation_type,
                        paper_evidence_ids=item.paper_evidence_ids,
                        code_evidence_ids=item.code_evidence_ids,
                        reason_codes=["human_review"],
                    )
                    for item in review.selections
                ]
                status = "accepted" if selections else "abstained"
        authority = "human_reviewed" if reviews else (
            "verified_model" if base.decision_source == "llm_verifier" else "derived_scorer"
        )
        return EffectiveAlignmentDecision(
            decision_id=decision_id,
            decision_version=base.decision_version,
            effective_revision=int(row["effective_revision"]),
            review_sequence=int(row["review_sequence"]),
            status=status,
            selections=selections,
            authority_level=authority,
            applied_review_ids=[item.review_id for item in reviews],
        )
