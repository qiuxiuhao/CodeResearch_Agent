from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


SCHEMA_VERSION = "1"
MAX_REASON_CODES = 100
MAX_ARTIFACT_REFS = 200
MAX_CASES_PER_RUN = 10_000

DatasetSplit = Literal["dev", "locked_test", "regression"]
DatasetSource = Literal["human_authored", "confirmed_bad_case", "synthetic_fixture"]
EvaluationMode = Literal["offline_recompute", "deterministic_fixture", "live_experiment"]
EvaluationComponent = Literal[
    "index", "retrieval", "agent", "alignment", "answer", "observability"
]
EvaluationRunStatus = Literal[
    "queued", "preparing", "running", "aggregating", "comparing",
    "completed", "partial", "failed", "cancelled",
]
CaseExecutionStatus = Literal[
    "queued", "running", "completed", "error", "skipped", "cancelled"
]
CaseEvaluationOutcome = Literal["passed", "failed", "not_evaluable", "indeterminate"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "created_at", "updated_at", "frozen_at", "started_at", "finished_at",
        "promoted_at", "observed_at", "verified_at", "next_attempt_at",
        check_fields=False,
    )
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation timestamps must be timezone-aware")
        return value.astimezone(UTC)


class EvaluationProviderBudget(StrictModel):
    max_requests: int = Field(default=0, ge=0, le=100_000)
    max_tokens: int = Field(default=0, ge=0)
    max_estimated_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=16)


class EvaluationSubject(StrictModel):
    schema_version: str = SCHEMA_VERSION
    subject_id: str = Field(min_length=1, max_length=128)
    subject_type: Literal[
        "code_commit", "worktree_patch", "configuration",
        "prompt_profile", "model_profile", "combined",
    ]
    code_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_tag: str | None = Field(default=None, max_length=128)
    worktree_patch_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_profile_ids: dict[str, str] = Field(default_factory=dict, max_length=100)
    model_profile_ids: dict[str, str] = Field(default_factory=dict, max_length=100)
    provider_revisions: dict[str, str] = Field(default_factory=dict, max_length=100)
    dependency_lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @property
    def formal_baseline_eligible(self) -> bool:
        return self.subject_type in {"code_commit", "combined"} and self.worktree_patch_hash is None


class EvaluationProvenance(StrictModel):
    schema_version: str = SCHEMA_VERSION
    subject_id: str
    dataset_version_id: str | None = None
    fixture_version: str | None = None
    repo_id: str | None = None
    reference_index_version_id: str | None = None
    candidate_index_version_id: str | None = None
    paper_id: str | None = None
    adapter_profile_hash: str | None = None
    metric_definition_hash: str | None = None
    created_at: datetime


class EvaluationDataset(StrictModel):
    schema_version: str = SCHEMA_VERSION
    dataset_id: str
    dataset_family_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    component_scope: list[EvaluationComponent] = Field(min_length=1, max_length=6)
    owner_scope_hash: str
    status: Literal["draft", "active", "retired"] = "draft"
    active_version_id: str | None = None
    created_at: datetime
    updated_at: datetime


class EvaluationDatasetVersion(StrictModel):
    schema_version: str = SCHEMA_VERSION
    dataset_version_id: str
    dataset_id: str
    version: str
    status: Literal["draft", "validating", "frozen", "superseded", "invalid"]
    parent_version_id: str | None = None
    case_count: int = Field(default=0, ge=0, le=MAX_CASES_PER_RUN)
    split_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    schema_hash: str
    gold_hash: str
    fixture_hash: str
    content_hash: str
    annotation_policy_version: str
    authorization_scope_hash: str
    provenance: EvaluationProvenance
    created_at: datetime
    frozen_at: datetime | None = None


class EvaluationArtifactRef(StrictModel):
    schema_version: str = SCHEMA_VERSION
    artifact_ref_id: str
    artifact_type: Literal[
        "dataset", "fixture", "gold", "prediction", "run", "trace", "checkpoint",
        "index_manifest", "retrieval_result", "answer", "alignment_decision", "report",
    ]
    artifact_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    repo_id: str | None = None
    index_version_id: str | None = None
    paper_id: str | None = None
    authority: Literal["gold", "business_fact", "derived_result", "diagnostic"]
    storage_kind: Literal[
        "evaluation_store", "business_store", "trace_store", "checkpoint_store",
        "fixture_catalog", "filesystem_fixture",
    ]
    storage_locator: str = Field(min_length=1, max_length=1_000)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    redaction_policy: str = Field(min_length=1, max_length=128)
    availability_status: Literal["available", "missing", "expired", "access_denied"]

    @field_validator("storage_locator")
    @classmethod
    def controlled_locator(cls, value: str) -> str:
        if value.startswith(("/", "~", "file://")) or ".." in value.split("/"):
            raise ValueError("storage_locator must use a controlled resolver locator")
        if ":" not in value:
            raise ValueError("storage_locator must include a resolver scheme")
        return value


class EvaluationFixtureBinding(StrictModel):
    schema_version: str = SCHEMA_VERSION
    repository_fixture_id: str
    repository_content_hash: str
    paper_fixture_id: str | None = None
    paper_content_hash: str | None = None
    reference_index_version_id: str | None = None
    reference_index_manifest_hash: str | None = None
    candidate_index_namespace: str | None = None
    fixture_version: str
    artifact_ref_ids: list[str] = Field(default_factory=list, max_length=MAX_ARTIFACT_REFS)


class IndexEvaluationInput(StrictModel):
    component: Literal["index"] = "index"
    repository_artifact_ref_ids: list[str] = Field(min_length=1, max_length=MAX_ARTIFACT_REFS)
    build_profile_id: str
    candidate_namespace_policy: Literal["temporary_database", "isolated_namespace"]


class RetrievalEvaluationInput(StrictModel):
    component: Literal["retrieval"] = "retrieval"
    query_artifact_ref_ids: list[str] = Field(min_length=1, max_length=MAX_ARTIFACT_REFS)
    retrieval_profile_id: str
    top_k: int = Field(default=20, ge=1, le=100)
    filters: dict[str, JsonValue] = Field(default_factory=dict)


class AgentEvaluationInput(StrictModel):
    component: Literal["agent"] = "agent"
    task_artifact_ref_ids: list[str] = Field(min_length=1, max_length=MAX_ARTIFACT_REFS)
    run_profile_id: str
    budget_profile_id: str
    fault_profile_id: str | None = None


class AlignmentEvaluationInput(StrictModel):
    component: Literal["alignment"] = "alignment"
    paper_artifact_ref_ids: list[str] = Field(min_length=1, max_length=MAX_ARTIFACT_REFS)
    profile_ids: list[str] = Field(min_length=1, max_length=1_000)
    alignment_model_profile_id: str
    deployment_id: str | None = None


class AnswerEvaluationInput(StrictModel):
    component: Literal["answer"] = "answer"
    answer_artifact_ref_ids: list[str] = Field(min_length=1, max_length=MAX_ARTIFACT_REFS)
    context_artifact_ref_ids: list[str] = Field(default_factory=list, max_length=MAX_ARTIFACT_REFS)
    answer_profile_id: str


class ObservabilityEvaluationInput(StrictModel):
    component: Literal["observability"] = "observability"
    trace_artifact_ref_ids: list[str] = Field(min_length=1, max_length=MAX_ARTIFACT_REFS)
    recorder_profile_id: str
    operation_taxonomy_version: str


EvaluationInput: TypeAlias = Annotated[
    IndexEvaluationInput | RetrievalEvaluationInput | AgentEvaluationInput |
    AlignmentEvaluationInput | AnswerEvaluationInput | ObservabilityEvaluationInput,
    Field(discriminator="component"),
]


class IndexGold(StrictModel):
    component: Literal["index"] = "index"
    required_entity_ids: list[str] = Field(default_factory=list)
    required_edge_ids: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    required_chunk_ids: list[str] = Field(default_factory=list)
    allowed_unresolved_symbols: list[str] = Field(default_factory=list)
    expected_manifest_fields: dict[str, JsonValue] = Field(default_factory=dict)
    expected_id_stability: dict[str, str] = Field(default_factory=dict)


class RetrievalGold(StrictModel):
    component: Literal["retrieval"] = "retrieval"
    required_entity_ids: list[str] = Field(default_factory=list)
    required_chunk_ids: list[str] = Field(default_factory=list)
    relevance_by_entity: dict[str, float] = Field(default_factory=dict)
    relevance_by_chunk: dict[str, float] = Field(default_factory=dict)
    required_paths: list[list[str]] = Field(default_factory=list)
    required_edge_types: list[str] = Field(default_factory=list)
    allowed_unresolved: list[str] = Field(default_factory=list)
    max_empty_results: int = Field(default=0, ge=0)


class AgentGold(StrictModel):
    component: Literal["agent"] = "agent"
    expected_route: str
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    allowed_tool_orders: list[list[str]] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    required_edge_ids: list[str] = Field(default_factory=list)
    expected_sufficient: bool
    expected_terminal_status: str
    max_tool_calls: int = Field(default=10, ge=0, le=100)
    max_replans: int = Field(default=2, ge=0, le=20)
    expected_partial_reason_codes: list[str] = Field(default_factory=list)


class AlignmentGoldSelection(StrictModel):
    code_entity_id: str
    relation_type: Literal[
        "implements", "partially_implements", "supports_training",
        "supports_inference", "configures",
    ]


class AlignmentGold(StrictModel):
    component: Literal["alignment"] = "alignment"
    profile_id: str
    gold_selections: list[AlignmentGoldSelection] = Field(default_factory=list)
    acceptable_alternative_sets: list[list[AlignmentGoldSelection]] = Field(default_factory=list)
    alignable: bool
    no_implementation_expected: bool = False
    required_paper_evidence_ids: list[str] = Field(default_factory=list)
    required_code_evidence_ids: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_implementation_has_no_selection(self) -> "AlignmentGold":
        if self.no_implementation_expected and self.gold_selections:
            raise ValueError("no-implementation gold cannot contain selections")
        return self


class AnswerGold(StrictModel):
    component: Literal["answer"] = "answer"
    required_answer_points: list[str] = Field(default_factory=list)
    optional_answer_points: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    allowed_citation_sets: list[list[str]] = Field(default_factory=list)
    required_claim_relations: list[str] = Field(default_factory=list)
    evidence_only_expected: bool = True
    partial_expected: bool = False


class ObservabilityGold(StrictModel):
    component: Literal["observability"] = "observability"
    required_operations: list[str] = Field(default_factory=list)
    required_parent_child_edges: list[tuple[str, str]] = Field(default_factory=list)
    required_links: list[dict[str, str]] = Field(default_factory=list)
    forbidden_attributes: list[str] = Field(default_factory=list)
    required_integrity_state: Literal["complete", "partial", "unknown"]
    allowed_integrity_flags: list[str] = Field(default_factory=list)
    max_drop_count: int = Field(default=0, ge=0)
    max_missing_span_count: int = Field(default=0, ge=0)


EvaluationGold: TypeAlias = Annotated[
    IndexGold | RetrievalGold | AgentGold | AlignmentGold | AnswerGold | ObservabilityGold,
    Field(discriminator="component"),
]


class IndexOutcome(StrictModel):
    component: Literal["index"] = "index"
    candidate_index_version_id: str
    entity_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    unresolved_symbols: list[str] = Field(default_factory=list)
    manifest_hash: str


class RetrievalOutcome(StrictModel):
    component: Literal["retrieval"] = "retrieval"
    ranked_entity_ids: list[str] = Field(default_factory=list)
    ranked_chunk_ids: list[str] = Field(default_factory=list)
    graph_paths: list[list[str]] = Field(default_factory=list)
    channel_status: dict[str, str] = Field(default_factory=dict)
    fallback_reason_codes: list[str] = Field(default_factory=list)


class AgentOutcome(StrictModel):
    component: Literal["agent"] = "agent"
    route: str
    plan_steps: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, JsonValue]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    sufficient: bool
    terminal_status: str
    partial_reason_codes: list[str] = Field(default_factory=list)


class AlignmentOutcome(StrictModel):
    component: Literal["alignment"] = "alignment"
    profile_id: str
    candidate_ids: list[str] = Field(default_factory=list)
    selections: list[AlignmentGoldSelection] = Field(default_factory=list)
    decision_status: str
    paper_evidence_ids: list[str] = Field(default_factory=list)
    code_evidence_ids: list[str] = Field(default_factory=list)
    candidate_probabilities: dict[str, float] = Field(default_factory=dict)


class AnswerOutcome(StrictModel):
    component: Literal["answer"] = "answer"
    answer_point_ids: list[str] = Field(default_factory=list)
    claims: list[dict[str, JsonValue]] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    partial: bool = False


class ObservabilityOutcome(StrictModel):
    component: Literal["observability"] = "observability"
    operation_names: list[str] = Field(default_factory=list)
    parent_child_edges: list[tuple[str, str]] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    observed_attribute_keys: list[str] = Field(default_factory=list)
    completeness: Literal["complete", "partial", "unknown"]
    integrity_flags: list[str] = Field(default_factory=list)
    drop_count: int = Field(default=0, ge=0)
    missing_span_count: int = Field(default=0, ge=0)


EvaluationOutcome: TypeAlias = Annotated[
    IndexOutcome | RetrievalOutcome | AgentOutcome | AlignmentOutcome |
    AnswerOutcome | ObservabilityOutcome,
    Field(discriminator="component"),
]


class EvaluationCase(StrictModel):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    stable_case_family_id: str
    dataset_version_id: str
    split: DatasetSplit
    source: DatasetSource
    component: EvaluationComponent
    fixture: EvaluationFixtureBinding
    repo_id: str
    reference_index_version_id: str | None = None
    paper_id: str | None = None
    input: EvaluationInput
    input_artifact_ref_ids: list[str] = Field(default_factory=list, max_length=MAX_ARTIFACT_REFS)
    gold: EvaluationGold
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = Field(default_factory=list, max_length=50)
    annotator_scope_hashes: list[str] = Field(default_factory=list, max_length=20)
    adjudication_status: Literal[
        "not_required", "pending", "agreed", "adjudicated", "disputed"
    ] = "not_required"
    provenance: EvaluationProvenance
    content_hash: str

    @model_validator(mode="after")
    def component_consistency(self) -> "EvaluationCase":
        if self.input.component != self.component or self.gold.component != self.component:
            raise ValueError("case, input, and gold components must match")
        if self.reference_index_version_id != self.fixture.reference_index_version_id:
            raise ValueError("case and fixture reference index versions must match")
        return self


class ExecutionEnvironment(StrictModel):
    schema_version: str = SCHEMA_VERSION
    environment_id: str
    python_version: str
    dependency_lock_hash: str
    os_name: str
    os_version: str
    cpu_profile: str
    gpu_profile: str | None = None
    memory_profile: str | None = None
    provider_region: str | None = None
    cache_profile: Literal["cold", "warm", "mixed", "not_applicable"]
    case_concurrency: int = Field(ge=1, le=1_000)
    provider_concurrency: int = Field(ge=0, le=1_000)
    environment_hash: str


class EvaluationRunFingerprint(StrictModel):
    schema_version: str = SCHEMA_VERSION
    dataset_version_id: str
    case_set_hash: str
    gold_hash: str
    subject_id: str
    metric_definition_hash: str
    adapter_profile_hash: str
    adapter_major_hash: str
    fixture_hash: str
    execution_mode: EvaluationMode
    environment_hash: str
    random_seed: int
    run_fingerprint_hash: str


class LiveTrialSpec(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trial_group_id: str
    repeat_count: int = Field(ge=1, le=100)
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None
    seed_supported: bool


class EvaluationPlan(StrictModel):
    schema_version: str = SCHEMA_VERSION
    plan_id: str
    dataset_version_id: str
    subject_id: str
    mode: EvaluationMode
    components: list[EvaluationComponent] = Field(min_length=1, max_length=6)
    adapter_versions: dict[str, str]
    metric_definition_ids: list[str]
    case_ids: list[str] = Field(min_length=1, max_length=MAX_CASES_PER_RUN)
    baseline_binding_id: str | None = None
    gate_config_version: str | None = None
    frozen_config_hash: str
    case_concurrency: int = Field(default=1, ge=1, le=100)
    provider_concurrency: int = Field(default=0, ge=0, le=20)
    provider_budget: EvaluationProviderBudget | None = None
    external_model_consent: bool = False
    random_seed: int = 0
    live_trial: LiveTrialSpec | None = None
    provenance: EvaluationProvenance

    @model_validator(mode="after")
    def live_requirements(self) -> "EvaluationPlan":
        if self.mode == "live_experiment":
            if not self.external_model_consent or self.provider_budget is None or self.live_trial is None:
                raise ValueError("live experiment requires consent, budget, and trial spec")
        elif self.live_trial is not None:
            raise ValueError("trial spec is only valid for live experiments")
        return self


class EvaluationRun(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    plan_id: str
    dataset_version_id: str
    subject_id: str
    mode: EvaluationMode
    status: EvaluationRunStatus
    run_fingerprint: EvaluationRunFingerprint
    environment_id: str
    trial_group_id: str | None = None
    repeat_index: int | None = Field(default=None, ge=0)
    repeat_count: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None
    attempt_number: int = Field(default=1, ge=1)
    retry_of_run_id: str | None = None
    cancel_requested: bool = False
    lease_owner_hash: str | None = None
    case_counts: dict[str, int] = Field(default_factory=dict)
    complete: bool = False
    incomplete_reason_codes: list[str] = Field(default_factory=list, max_length=MAX_REASON_CODES)
    error_code: str | None = None
    provenance: EvaluationProvenance
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class EvaluationBaselineBinding(StrictModel):
    schema_version: str = SCHEMA_VERSION
    baseline_binding_id: str
    dataset_version_id: str
    component: EvaluationComponent
    evaluation_mode: EvaluationMode
    dataset_source_profile: Literal[
        "human_authored", "confirmed_bad_case", "synthetic_fixture", "mixed"
    ]
    gate_config_version: str
    baseline_run_id: str
    subject_id: str
    status: Literal["active", "superseded", "retired"]
    promoted_by_scope_hash: str
    promotion_reason_code: str
    created_at: datetime
    promoted_at: datetime


class CaseResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    result_id: str
    evaluation_run_id: str
    case_id: str
    component: EvaluationComponent
    execution_status: CaseExecutionStatus
    evaluation_outcome: CaseEvaluationOutcome | None = None
    complete: bool
    incomplete_reason_codes: list[str] = Field(default_factory=list, max_length=MAX_REASON_CODES)
    execution_error_code: str | None = None
    quality_failure_codes: list[str] = Field(default_factory=list, max_length=MAX_REASON_CODES)
    outcome: EvaluationOutcome | None = None
    business_run_id: str | None = None
    trace_id: str | None = None
    output_artifact_refs: list[EvaluationArtifactRef] = Field(default_factory=list, max_length=MAX_ARTIFACT_REFS)
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: dict[str, int] = Field(default_factory=dict)
    estimated_cost: float | None = Field(default=None, ge=0)
    content_hash: str
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def status_consistency(self) -> "CaseResult":
        if self.execution_status == "error":
            if not self.execution_error_code or self.evaluation_outcome is not None:
                raise ValueError("execution errors require an error code and no quality outcome")
        if self.execution_status == "completed" and self.evaluation_outcome is None:
            raise ValueError("completed execution requires an evaluation outcome")
        if self.evaluation_outcome == "failed" and not self.quality_failure_codes:
            raise ValueError("quality failure requires quality_failure_codes")
        if self.evaluation_outcome == "indeterminate" and self.complete:
            raise ValueError("indeterminate result cannot be complete")
        if self.outcome is not None and self.outcome.component != self.component:
            raise ValueError("result component and typed outcome must match")
        return self


class MetricDefinition(StrictModel):
    schema_version: str = SCHEMA_VERSION
    metric_definition_id: str
    name: str
    version: str
    component: EvaluationComponent
    direction: Literal["higher_is_better", "lower_is_better", "zero_required"]
    aggregation: Literal["count", "ratio", "mean", "macro_mean", "percentile", "calibration"]
    denominator_policy: str
    empty_input_policy: Literal["zero", "one", "null", "error"]
    requires_complete_input: bool
    subgroup_keys: list[str] = Field(default_factory=list)
    config_hash: str


class MetricResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    metric_result_id: str
    evaluation_run_id: str
    metric_definition_id: str
    split: DatasetSplit | Literal["all"]
    subgroup: dict[str, str] = Field(default_factory=dict)
    value: float | None
    numerator: float | None
    denominator: float | None
    sample_count: int = Field(ge=0)
    complete: bool
    incomplete_reason_codes: list[str] = Field(default_factory=list)
    confidence_interval: tuple[float, float] | None = None
    artifact_ref_ids: list[str] = Field(default_factory=list)
    computed_at: datetime


class ComparisonScope(StrictModel):
    schema_version: str = SCHEMA_VERSION
    common_case_ids: list[str] = Field(default_factory=list)
    excluded_baseline_case_ids: list[str] = Field(default_factory=list)
    excluded_candidate_case_ids: list[str] = Field(default_factory=list)
    comparable_metric_definition_ids: list[str] = Field(default_factory=list)
    incompatible_metric_definition_ids: list[str] = Field(default_factory=list)
    compatibility: Literal["compatible", "partially_compatible", "incompatible"]
    incompatibility_reasons: list[str] = Field(default_factory=list)


class MetricDelta(StrictModel):
    metric_definition_id: str
    subgroup: dict[str, str] = Field(default_factory=dict)
    baseline_value: float | None
    candidate_value: float | None
    absolute_delta: float | None
    relative_delta: float | None
    numerator: float | None = None
    denominator: float | None = None
    sample_count: int = Field(ge=0)
    complete: bool


class RegressionComparison(StrictModel):
    schema_version: str = SCHEMA_VERSION
    comparison_id: str
    baseline_binding_id: str
    baseline_run_id: str
    candidate_run_id: str
    baseline_subject_id: str
    candidate_subject_id: str
    scope: ComparisonScope
    metric_deltas: list[MetricDelta] = Field(default_factory=list)
    subgroup_deltas: list[MetricDelta] = Field(default_factory=list)
    status: Literal["pending", "ready", "invalid"]
    created_at: datetime


class GateRule(StrictModel):
    schema_version: str = SCHEMA_VERSION
    rule_id: str
    metric_definition_id: str
    scope: Literal["overall", "split", "source", "repo", "pair", "tag", "type"]
    subgroup_filter: dict[str, str] = Field(default_factory=dict)
    comparison: Literal[
        "equal_zero", "min_value", "max_value", "max_absolute_drop", "max_relative_drop"
    ]
    threshold: float
    min_sample_count: int = Field(default=1, ge=1)
    incomplete_policy: Literal["block", "warning", "ignore"]
    severity: Literal["warning", "block"]

    @model_validator(mode="after")
    def scope_filter_consistency(self) -> "GateRule":
        if self.scope == "overall" and self.subgroup_filter:
            raise ValueError("overall gate rule cannot define a subgroup filter")
        if self.scope != "overall" and self.scope not in self.subgroup_filter:
            raise ValueError("subgroup gate rule must freeze its scoped subgroup")
        return self


class RegressionGateConfig(StrictModel):
    schema_version: str = SCHEMA_VERSION
    gate_config_version: str
    profile_type: Literal["ci", "release", "manual"]
    hard_rules: list[GateRule] = Field(default_factory=list)
    quality_rules: list[GateRule] = Field(default_factory=list)
    performance_rules: list[GateRule] = Field(default_factory=list)
    critical_subgroups: list[dict[str, str]] = Field(default_factory=list)
    minimum_live_repeat_count: int | None = Field(default=None, ge=2)
    config_hash: str
    created_at: datetime


class GateRuleResult(StrictModel):
    rule_id: str
    verdict: Literal["passed", "warning", "blocked", "indeterminate"]
    numerator: float | None = None
    denominator: float | None = None
    sample_count: int = Field(ge=0)
    baseline_value: float | None = None
    candidate_value: float | None = None
    absolute_delta: float | None = None
    relative_delta: float | None = None
    evidence_artifact_ref_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class RegressionGate(StrictModel):
    schema_version: str = SCHEMA_VERSION
    gate_id: str
    comparison_id: str
    gate_config_version: str
    hard_invariants: list[GateRuleResult] = Field(default_factory=list)
    quality_rules: list[GateRuleResult] = Field(default_factory=list)
    performance_rules: list[GateRuleResult] = Field(default_factory=list)
    verdict: Literal["passed", "blocked", "indeterminate"]
    reason_codes: list[str] = Field(default_factory=list)
    evaluated_at: datetime


BadCaseSymptom = Literal[
    "wrong_answer", "partial_answer", "empty_result", "wrong_alignment",
    "invalid_citation", "unsupported_claim", "timeout", "budget_exhausted",
    "unexpected_abstention", "false_accept", "trace_incomplete",
]
BadCaseRootCause = Literal[
    "dataset_invalid", "profile_extraction_error", "index_missing_entity",
    "index_wrong_edge", "retrieval_miss", "retrieval_rank_error", "graph_path_missing",
    "reranker_regression", "router_error", "plan_invalid", "tool_selection_error",
    "tool_argument_error", "tool_empty", "evidence_checker_error", "context_truncation",
    "provider_error", "alignment_candidate_miss", "alignment_feature_error",
    "alignment_scoring_error", "calibration_error", "abstention_threshold_error",
    "nondeterminism", "telemetry_drop", "unknown",
]


class RootCauseSuggestion(StrictModel):
    root_cause: BadCaseRootCause
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_ref_ids: list[str] = Field(default_factory=list)
    analyzer_version: str


class FixReference(StrictModel):
    schema_version: str = SCHEMA_VERSION
    fix_type: Literal[
        "code_commit", "configuration", "prompt_profile", "model_profile", "dataset_fix"
    ]
    reference_id: str
    content_hash: str


class BadCase(StrictModel):
    schema_version: str = SCHEMA_VERSION
    bad_case_id: str
    fingerprint: str
    source_result_id: str
    source_evaluation_run_id: str
    source_trace_id: str | None = None
    stable_case_family_id: str
    case_id: str
    component: EvaluationComponent
    symptom: BadCaseSymptom
    trigger_type: Literal[
        "execution_error", "quality_failure", "gold_invalid",
        "not_evaluable", "telemetry_incomplete",
    ]
    suggested_root_causes: list[RootCauseSuggestion] = Field(default_factory=list)
    confirmed_root_cause: BadCaseRootCause | None = None
    status: Literal[
        "open", "triaged", "confirmed", "fixing", "fixed", "verified", "closed", "rejected"
    ]
    revision: int = Field(default=0, ge=0)
    severity: Literal["low", "medium", "high", "critical"]
    evidence_ref_ids: list[str] = Field(default_factory=list)
    fix_reference: FixReference | None = None
    verification_id: str | None = None
    first_seen_run_id: str
    last_seen_run_id: str
    occurrence_count: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime


class BadCaseOccurrence(StrictModel):
    schema_version: str = SCHEMA_VERSION
    occurrence_id: str
    bad_case_id: str
    evaluation_run_id: str
    case_result_id: str
    trace_id: str | None = None
    subject_id: str
    observed_at: datetime


class BadCaseEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str
    bad_case_id: str
    sequence: int = Field(ge=1)
    from_status: str | None = None
    to_status: str
    actor_scope_hash: str
    based_on_revision: int = Field(ge=0)
    reason_code: str
    note_hash: str | None = None
    artifact_ref_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class RegressionCasePromotion(StrictModel):
    schema_version: str = SCHEMA_VERSION
    promotion_id: str
    bad_case_id: str
    source_dataset_version_id: str
    target_dataset_version_id: str
    new_case_id: str
    source_trace_id: str | None = None
    pre_fix_reproduction_result_id: str | None = None
    reproduction_status: Literal["pending", "reproduced", "not_reproducible", "rejected"]
    fix_reference: FixReference | None = None
    gold_review_status: Literal["pending", "approved", "rejected"]
    fixture_minimization_status: Literal["pending", "complete", "not_possible"]
    created_at: datetime


class BadCaseVerification(StrictModel):
    schema_version: str = SCHEMA_VERSION
    verification_id: str
    bad_case_id: str
    verification_run_id: str
    verification_case_result_id: str
    relevant_metric_result_ids: list[str] = Field(default_factory=list)
    required_gate_rule_ids: list[str] = Field(default_factory=list)
    case_passed: bool
    relevant_rules_passed: bool
    regression_case_passed: bool
    verified_at: datetime


class ReplayManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    replay_manifest_id: str
    replay_type: Literal["analysis", "offline", "live"]
    source_evaluation_run_id: str
    source_business_run_id: str | None = None
    source_subject_id: str
    replay_subject_id: str
    source_trace_id: str | None = None
    source_checkpoint_id: str | None = None
    required_artifact_ref_ids: list[str] = Field(default_factory=list)
    readiness: Literal["ready", "not_ready", "consent_required", "artifact_missing"]
    reason_codes: list[str] = Field(default_factory=list)
    external_model_consent: bool = False
    budget: EvaluationProviderBudget | None = None
    trial_spec: LiveTrialSpec | None = None
    execution_requested: bool = False
    content_hash: str


class BusinessEquivalenceContract(StrictModel):
    schema_version: str = SCHEMA_VERSION
    contract_id: str
    component: EvaluationComponent
    required_equal_fields: list[str] = Field(default_factory=list)
    ignored_fields: list[str] = Field(default_factory=list)
    order_insensitive_fields: list[str] = Field(default_factory=list)
    float_tolerances: dict[str, float] = Field(default_factory=dict)
    normalizer_version: str
    config_hash: str


class EvaluationRunCreateRequest(StrictModel):
    dataset_version_id: str
    subject_id: str
    environment_id: str
    mode: EvaluationMode
    components: list[EvaluationComponent] = Field(min_length=1, max_length=6)
    case_ids: list[str] = Field(default_factory=list, max_length=MAX_CASES_PER_RUN)
    adapter_versions: dict[str, str] = Field(default_factory=dict)
    metric_definition_ids: list[str] = Field(default_factory=list)
    baseline_binding_id: str | None = None
    gate_config_version: str | None = None
    case_concurrency: int = Field(default=1, ge=1, le=100)
    provider_concurrency: int = Field(default=0, ge=0, le=20)
    provider_budget: EvaluationProviderBudget | None = None
    external_model_consent: bool = False
    random_seed: int = 0
    live_trial: LiveTrialSpec | None = None
    retry_of_run_id: str | None = None


class BaselinePromotionRequest(StrictModel):
    dataset_version_id: str
    component: EvaluationComponent
    evaluation_mode: EvaluationMode
    gate_config_version: str
    baseline_run_id: str
    promotion_reason_code: str


class BadCaseTransitionRequest(StrictModel):
    based_on_revision: int = Field(ge=0)
    reason_code: str
    confirmed_root_cause: BadCaseRootCause | None = None
    fix_reference: FixReference | None = None
    verification: BadCaseVerification | None = None
    artifact_ref_ids: list[str] = Field(default_factory=list)


class ComparisonCreateRequest(StrictModel):
    baseline_binding_id: str
    candidate_run_id: str


class RegressionPromotionRequest(StrictModel):
    source_dataset_version_id: str
    target_dataset_version_id: str
    new_case_id: str
    source_trace_id: str | None = None
    pre_fix_reproduction_result_id: str | None = None
    reproduced: bool = False
    fix_reference: FixReference | None = None
    regression_case: EvaluationCase | None = None
