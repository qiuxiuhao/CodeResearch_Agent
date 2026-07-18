from __future__ import annotations

from datetime import UTC, datetime

from backend.app.alignment.calibrator import IdentityCalibrator
from backend.app.alignment.schemas import (
    AlignmentCandidate,
    AlignmentCandidateScore,
    AlignmentDecision,
    AlignmentDecisionConfidence,
    AlignmentFeatureVector,
    AlignmentRelation,
    AlignmentSelection,
    PaperModuleProfile,
)
from backend.app.alignment.stable_ids import decision_id, score_id, selection_id


SCORER_VERSION = "weighted-scorer-v1"
DECISION_VERSION = "alignment-decision-v1"
DEFAULT_WEIGHTS = {
    "name": 0.22,
    "semantic": 0.16,
    "role": 0.12,
    "structure": 0.12,
    "input_output": 0.10,
    "shape": 0.08,
    "formula_variable": 0.08,
    "figure_topology": 0.05,
    "evidence_quality": 0.07,
}


def score_feature_vector(
    vector: AlignmentFeatureVector,
    *,
    calibrator=None,
    weights: dict[str, float] | None = None,
) -> AlignmentCandidateScore:
    weights = weights or DEFAULT_WEIGHTS
    available = [item for item in vector.features if item.status == "available" and item.normalized_value is not None]
    denominator = sum(weights.get(item.feature_name, 0.0) for item in available)
    contributions = {
        item.feature_name: weights.get(item.feature_name, 0.0) * float(item.normalized_value)
        for item in available
    }
    raw = sum(contributions.values()) / denominator if denominator else 0.0
    adjusted = raw * vector.coverage_penalty
    calibrator = calibrator or IdentityCalibrator()
    probability = calibrator.predict(adjusted)
    reasons: list[str] = []
    if vector.available_weight_ratio < vector.required_weight_ratio:
        reasons.append("feature_coverage_below_required")
    if any(item.status == "required_missing" for item in vector.features):
        reasons.append("required_feature_missing")
    return AlignmentCandidateScore(
        score_id=score_id(candidate_id_value=vector.candidate_id, scorer_version=SCORER_VERSION),
        alignment_run_id=vector.alignment_run_id,
        profile_id=vector.profile_id,
        candidate_id=vector.candidate_id,
        raw_available_feature_score=raw,
        available_weight_ratio=vector.available_weight_ratio,
        required_weight_ratio=vector.required_weight_ratio,
        coverage_penalty=vector.coverage_penalty,
        coverage_adjusted_score=adjusted,
        calibrated_match_probability=probability,
        calibration_profile_id=getattr(calibrator, "profile_id", None),
        feature_contributions=contributions,
        reason_codes=reasons,
    )


def build_profile_decision(
    *,
    profile: PaperModuleProfile,
    candidates: list[AlignmentCandidate],
    scores: list[AlignmentCandidateScore],
    accept_threshold: float = 0.72,
    review_threshold: float = 0.45,
    accept_margin: float = 0.08,
    max_selections: int = 5,
    strong_negative_evidence: bool = False,
    human_confirmed_no_implementation: bool = False,
) -> AlignmentDecision:
    candidate_by_id = {item.candidate_id: item for item in candidates}
    ranked = sorted(scores, key=lambda item: (-(item.calibrated_match_probability or 0.0), item.candidate_id))
    top = ranked[0].calibrated_match_probability if ranked else 0.0
    second = ranked[1].calibrated_match_probability if len(ranked) > 1 else 0.0
    margin = max(0.0, (top or 0.0) - (second or 0.0))
    eligible = [
        item
        for item in ranked
        if (item.calibrated_match_probability or 0.0) >= accept_threshold
        and item.available_weight_ratio >= item.required_weight_ratio
        and "required_feature_missing" not in item.reason_codes
    ][:max_selections]

    identifier = decision_id(
        run_id=profile.alignment_run_id,
        profile_id_value=profile.profile_id,
        decision_version=DECISION_VERSION,
    )
    selections = [
        _selection(identifier, profile, candidate_by_id[item.candidate_id], item)
        for item in eligible
        if item.candidate_id in candidate_by_id
    ]
    if selections and margin >= accept_margin:
        status = "accepted"
        reasons = ["candidate_threshold_met", "coverage_gate_met", "margin_gate_met"]
    elif strong_negative_evidence and human_confirmed_no_implementation:
        status = "no_implementation"
        selections = []
        reasons = ["strong_negative_evidence", "human_review_confirmed"]
    elif ranked and (top or 0.0) >= review_threshold:
        status = "needs_review"
        selections = [
            _selection(identifier, profile, candidate_by_id[item.candidate_id], item)
            for item in ranked[:max_selections]
            if item.candidate_id in candidate_by_id
        ]
        reasons = ["review_band_or_small_margin"]
    else:
        status = "abstained"
        selections = []
        reasons = ["insufficient_alignment_evidence"]
    set_score = sum(item.calibrated_match_probability or 0.0 for item in eligible) / len(eligible) if eligible else None
    return AlignmentDecision(
        decision_id=identifier,
        alignment_run_id=profile.alignment_run_id,
        profile_id=profile.profile_id,
        decision_version=DECISION_VERSION,
        status=status,
        selections=selections,
        set_score=set_score,
        set_coverage=min(1.0, len(selections) / max(1, len(ranked))) if selections else 0.0,
        set_compatibility=1.0 if len({item.candidate_id for item in selections}) == len(selections) else 0.0,
        confidence=AlignmentDecisionConfidence(
            set_confidence=set_score,
            auto_accept_probability=(set_score if status == "accepted" else None),
            has_implementation_probability=(max((item.calibrated_match_probability or 0.0 for item in ranked), default=0.0)),
        ),
        top_margin=margin,
        decision_source="scorer",
        scorer_profile_id=SCORER_VERSION,
        reason_codes=reasons,
        created_at=datetime.now(UTC),
    )


def _selection(
    decision_identifier: str,
    profile: PaperModuleProfile,
    candidate: AlignmentCandidate,
    score: AlignmentCandidateScore,
) -> AlignmentSelection:
    relation = _relation(profile)
    return AlignmentSelection(
        selection_id=selection_id(
            decision_id_value=decision_identifier,
            candidate_id_value=candidate.candidate_id,
            relation_type=relation,
        ),
        candidate_id=candidate.candidate_id,
        relation_type=relation,
        raw_score=score.coverage_adjusted_score,
        calibrated_match_probability=score.calibrated_match_probability,
        paper_evidence_ids=profile.evidence_ids,
        code_evidence_ids=candidate.code_evidence_ids,
        reason_codes=["selected_by_weighted_scorer"],
    )


def _relation(profile: PaperModuleProfile) -> AlignmentRelation:
    return {
        "training_strategy": "supports_training",
        "inference_strategy": "supports_inference",
        "configuration": "configures",
        "general_contribution": "partially_implements",
    }.get(profile.profile_type, "implements")  # type: ignore[return-value]
