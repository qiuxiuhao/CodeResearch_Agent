from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import (
    EvaluationCase,
    EvaluationDatasetVersion,
    FixReference,
    RegressionCasePromotion,
)
from backend.app.evaluation.stable_ids import stable_id
from backend.app.evaluation.store_protocol import EvaluationStoreError, EvaluationStoreProtocol


class PromotionService:
    def __init__(self, store: EvaluationStoreProtocol) -> None:
        self.store = store

    def promote(
        self,
        *,
        bad_case_id: str,
        source_dataset_version_id: str,
        target_dataset_version_id: str,
        new_case_id: str,
        source_trace_id: str | None,
        pre_fix_reproduction_result_id: str | None,
        reproduced: bool,
        fix_reference: FixReference | None = None,
        regression_case: EvaluationCase | None = None,
    ) -> RegressionCasePromotion:
        bad_case = self.store.get_bad_case(bad_case_id)
        if bad_case.status not in {"confirmed", "fixing", "fixed", "verified"}:
            raise EvaluationStoreError("promotion_not_ready", bad_case.status)
        if reproduced and regression_case is None:
            raise EvaluationStoreError("regression_case_required")
        if regression_case is not None:
            if regression_case.case_id != new_case_id:
                raise EvaluationStoreError("regression_case_identity_mismatch")
            if regression_case.dataset_version_id != target_dataset_version_id:
                raise EvaluationStoreError("regression_case_dataset_mismatch")
            try:
                self.store.get_dataset_version(target_dataset_version_id)
            except EvaluationStoreError as exc:
                if exc.error_code != "evaluation_dataset_version_not_found":
                    raise
                source = self.store.get_dataset_version(source_dataset_version_id)
                target = EvaluationDatasetVersion(
                    dataset_version_id=target_dataset_version_id,
                    dataset_id=source.dataset_id,
                    version=f"{source.version}+regression",
                    status="draft",
                    parent_version_id=source.dataset_version_id,
                    schema_hash=source.schema_hash,
                    gold_hash=source.gold_hash,
                    fixture_hash=source.fixture_hash,
                    content_hash=source.content_hash,
                    annotation_policy_version=source.annotation_policy_version,
                    authorization_scope_hash=source.authorization_scope_hash,
                    provenance=source.provenance,
                    created_at=datetime.now(UTC),
                )
                self.store.save_dataset_version(target)
            self.store.save_case(regression_case)
        promotion = RegressionCasePromotion(
            promotion_id=stable_id("promotion", [bad_case_id, target_dataset_version_id, new_case_id]),
            bad_case_id=bad_case_id,
            source_dataset_version_id=source_dataset_version_id,
            target_dataset_version_id=target_dataset_version_id,
            new_case_id=new_case_id,
            source_trace_id=source_trace_id,
            pre_fix_reproduction_result_id=pre_fix_reproduction_result_id,
            reproduction_status="reproduced" if reproduced else "pending",
            fix_reference=fix_reference,
            gold_review_status="approved" if reproduced else "pending",
            fixture_minimization_status="complete" if reproduced else "pending",
            created_at=datetime.now(UTC),
        )
        self.store.save_promotion(promotion)
        return promotion

    @staticmethod
    def require_reproduced_before_freeze(promotion: RegressionCasePromotion) -> None:
        if promotion.reproduction_status != "reproduced" or not promotion.pre_fix_reproduction_result_id:
            raise EvaluationStoreError("regression_case_not_reproduced")
