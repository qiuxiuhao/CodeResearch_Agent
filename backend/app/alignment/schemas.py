from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


AlignmentSource = Literal[
    "deterministic_rule",
    "legacy_alignment",
    "retrieval_sparse",
    "retrieval_dense",
    "code_graph",
    "figure_vlm",
    "structured_llm",
    "scorer",
    "calibrator",
    "llm_verifier",
    "human_review",
]
ProfileType = Literal[
    "module",
    "formula",
    "figure_module",
    "training_strategy",
    "inference_strategy",
    "configuration",
    "general_contribution",
]
ProfileGranularity = Literal[
    "paper",
    "section",
    "contribution",
    "figure_node",
    "formula",
]
AlignmentRelation = Literal[
    "implements",
    "partially_implements",
    "supports_training",
    "supports_inference",
    "configures",
]
DecisionStatus = Literal["accepted", "abstained", "needs_review", "no_implementation"]
RunStatus = Literal[
    "queued",
    "profiling",
    "recalling",
    "featurizing",
    "scoring",
    "verifying",
    "ready",
    "active",
    "failed",
    "superseded",
    "cancelled",
]
AuthorityLevel = Literal[
    "legacy_heuristic",
    "derived_scorer",
    "verified_model",
    "human_reviewed",
]
EvidenceRole = Literal[
    "alignment_hypothesis",
    "alignment_decision",
    "code_fact",
    "paper_fact",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperModuleProfile(StrictModel):
    schema_version: str = "1"
    profile_id: str
    alignment_run_id: str
    repo_id: str
    index_version_id: str
    paper_id: str
    profile_type: ProfileType
    granularity: ProfileGranularity
    parent_profile_id: str | None = None
    source_group_key: str
    paper_entity_ids: list[str] = Field(default_factory=list)
    canonical_name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    abbreviations: list[str] = Field(default_factory=list)
    role: str | None = None
    description: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    formula_symbols: list[str] = Field(default_factory=list)
    figure_neighbor_ids: list[str] = Field(default_factory=list)
    contribution_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    extraction_sources: list[AlignmentSource] = Field(default_factory=list)
    content_hash: str
    extractor_version: str
    profile_generation_version: str
    profile_quality: float = Field(ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CandidateSourceContribution(StrictModel):
    source: AlignmentSource
    source_rank: int | None = Field(default=None, ge=1)
    source_score: float | None = None
    normalized_contribution: float | None = Field(default=None, ge=0.0)
    evidence_ids: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AlignmentCandidate(StrictModel):
    schema_version: str = "1"
    candidate_id: str
    alignment_run_id: str
    profile_id: str
    code_entity_id: str
    candidate_status: Literal["recalled", "scored", "pruned"] = "recalled"
    source_contributions: list[CandidateSourceContribution] = Field(default_factory=list)
    best_source_rank: int | None = Field(default=None, ge=1)
    code_evidence_ids: list[str] = Field(default_factory=list)
    retrieval_chunk_ids: list[str] = Field(default_factory=list)
    generated_at: datetime


class AlignmentFeatureValue(StrictModel):
    feature_name: str
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    normalized_value: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["available", "missing", "required_missing", "not_applicable"]
    missing_reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str
    extractor_version: str

    @property
    def available(self) -> bool:
        return self.status == "available"


class AlignmentFeatureVector(StrictModel):
    schema_version: str = "1"
    vector_id: str
    alignment_run_id: str
    profile_id: str
    candidate_id: str
    features: list[AlignmentFeatureValue]
    available_weight_ratio: float = Field(ge=0.0, le=1.0)
    required_weight_ratio: float = Field(gt=0.0, le=1.0)
    coverage_penalty: float = Field(ge=0.0, le=1.0)
    feature_schema_version: str
    content_hash: str


class AlignmentCandidateScore(StrictModel):
    schema_version: str = "1"
    score_id: str
    alignment_run_id: str
    profile_id: str
    candidate_id: str
    raw_available_feature_score: float = Field(ge=0.0, le=1.0)
    available_weight_ratio: float = Field(ge=0.0, le=1.0)
    required_weight_ratio: float = Field(gt=0.0, le=1.0)
    coverage_penalty: float = Field(ge=0.0, le=1.0)
    coverage_adjusted_score: float = Field(ge=0.0, le=1.0)
    calibrated_match_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_profile_id: str | None = None
    feature_contributions: dict[str, float] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)


class AlignmentSelection(StrictModel):
    selection_id: str
    candidate_id: str
    relation_type: AlignmentRelation
    raw_score: float | None = Field(default=None, ge=0.0, le=1.0)
    calibrated_match_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    paper_evidence_ids: list[str] = Field(default_factory=list)
    code_evidence_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class AlignmentDecisionConfidence(StrictModel):
    set_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_accept_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    has_implementation_probability: float | None = Field(default=None, ge=0.0, le=1.0)


class AlignmentDecision(StrictModel):
    schema_version: str = "1"
    decision_id: str
    alignment_run_id: str
    profile_id: str
    decision_version: str
    status: DecisionStatus
    selections: list[AlignmentSelection] = Field(default_factory=list)
    set_score: float | None = Field(default=None, ge=0.0, le=1.0)
    set_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    set_compatibility: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: AlignmentDecisionConfidence
    top_margin: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_source: AlignmentSource
    scorer_profile_id: str
    verifier_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def validate_selection_state(self) -> "AlignmentDecision":
        if self.status == "accepted" and not self.selections:
            raise ValueError("accepted decision requires at least one selection")
        if self.status in {"abstained", "no_implementation"} and self.selections:
            raise ValueError(f"{self.status} decision cannot contain selections")
        return self


class AlignmentSelectionProposal(StrictModel):
    candidate_id: str
    relation_type: AlignmentRelation
    evidence_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class AlignmentVerification(StrictModel):
    schema_version: str = "1"
    verification_id: str
    alignment_run_id: str
    profile_id: str
    allowed_candidate_ids: list[str]
    proposed_selections: list[AlignmentSelectionProposal] = Field(default_factory=list)
    verdict: Literal["accept", "abstain", "needs_review"]
    evidence_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    model_revision: str | None = None
    prompt_version: str
    status: Literal["success", "fallback", "failed", "skipped"]
    token_usage: dict[str, int] = Field(default_factory=dict)


class AlignmentReviewSelection(StrictModel):
    candidate_id: str
    relation_type: AlignmentRelation
    paper_evidence_ids: list[str] = Field(default_factory=list)
    code_evidence_ids: list[str] = Field(default_factory=list)


class AlignmentReview(StrictModel):
    schema_version: str = "1"
    review_id: str
    decision_id: str
    action: Literal[
        "accept",
        "reject",
        "replace_candidate",
        "accept_multiple",
        "mark_no_implementation",
        "add_note",
    ]
    selections: list[AlignmentReviewSelection] = Field(default_factory=list)
    note: str | None = None
    reviewer_scope_hash: str
    based_on_effective_revision: int = Field(ge=0)
    review_sequence: int = Field(ge=1)
    created_at: datetime


class EffectiveAlignmentDecision(StrictModel):
    decision_id: str
    decision_version: str
    effective_revision: int = Field(ge=0)
    review_sequence: int = Field(ge=0)
    status: DecisionStatus
    selections: list[AlignmentSelection] = Field(default_factory=list)
    authority_level: AuthorityLevel
    applied_review_ids: list[str] = Field(default_factory=list)


class AlignmentRun(StrictModel):
    schema_version: str = "1"
    run_id: str
    repo_id: str
    index_version_id: str
    paper_id: str
    input_hash: str
    model_profile_id: str
    attempt_number: int = Field(ge=1)
    retry_of_run_id: str | None = None
    status: RunStatus
    cancel_requested: bool = False
    current_stage: str | None = None
    profile_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    decision_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    abstained_count: int = Field(default=0, ge=0)
    needs_review_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None


class AlignmentModelProfile(StrictModel):
    schema_version: str = "1"
    model_profile_id: str
    profile_extractor_version: str
    profile_llm_provider: str | None = None
    profile_llm_model: str | None = None
    profile_llm_revision: str | None = None
    profile_prompt_version: str | None = None
    figure_vlm_provider: str | None = None
    figure_vlm_model: str | None = None
    figure_vlm_revision: str | None = None
    figure_analysis_version: str
    candidate_generator_versions: dict[str, str] = Field(default_factory=dict)
    dense_retrieval_profile_hash: str | None = None
    sparse_retrieval_generation: str | None = None
    graph_policy_version: str
    legacy_alignment_version: str
    feature_schema_version: str
    scorer_version: str
    weight_config_version: str
    calibration_method: str
    calibration_version: str
    thresholds: dict[str, float] = Field(default_factory=dict)
    verifier_provider: str | None = None
    verifier_model: str | None = None
    verifier_revision: str | None = None
    verifier_prompt_version: str | None = None
    config_hash: str


class AlignmentDeployment(StrictModel):
    schema_version: str = "1"
    deployment_id: str
    deployment_name: str
    repo_id: str
    index_version_id: str
    paper_id: str
    model_profile_id: str
    active_run_id: str
    created_at: datetime
    updated_at: datetime


class AlignmentRunCreateRequest(StrictModel):
    paper_id: str = Field(min_length=1, max_length=500)
    index_version_id: str | None = None
    model_profile_id: str = Field(default="alignment-default-v1", min_length=1, max_length=200)
    verifier_enabled: bool = False
    external_text_consent: bool = False
    retry_of_run_id: str | None = None


class AlignmentReviewRequest(StrictModel):
    action: Literal[
        "accept",
        "reject",
        "replace_candidate",
        "accept_multiple",
        "mark_no_implementation",
        "add_note",
    ]
    selections: list[AlignmentReviewSelection] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=4_000)
    based_on_effective_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_review_action(self) -> "AlignmentReviewRequest":
        if self.action in {"accept", "reject", "replace_candidate", "accept_multiple"} and not self.selections:
            raise ValueError(f"{self.action} requires at least one existing candidate selection")
        if self.action == "mark_no_implementation":
            if self.selections:
                raise ValueError("mark_no_implementation cannot contain selections")
            if not (self.note or "").strip():
                raise ValueError("mark_no_implementation requires a note")
        if self.action == "add_note" and not (self.note or "").strip():
            raise ValueError("add_note requires a note")
        return self


class AlignmentDeploymentRequest(StrictModel):
    index_version_id: str
    paper_id: str
    model_profile_id: str
    active_run_id: str


class AlignmentToolItem(StrictModel):
    entity_id: str
    profile_id: str | None = None
    decision_id: str | None = None
    source: str
    authority_level: AuthorityLevel
    evidence_role: EvidenceRole
    run_id: str | None = None
    model_profile_id: str | None = None
    deployment_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str = ""
