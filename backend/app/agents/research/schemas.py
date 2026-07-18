from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from backend.app.retrieval.schemas import AnswerCitation, ContextBundle, QueryType


ToolName = Literal[
    "search_hybrid",
    "get_symbol_source",
    "get_graph_neighbors",
    "get_call_path",
    "get_model_flow",
    "search_paper",
    "get_alignment",
    "inspect_config",
]
ResearchRoute = Literal["direct", "planned"]
ResearchRunStatus = Literal[
    "queued",
    "routing",
    "planning",
    "retrieving",
    "executing",
    "assessing",
    "replanning",
    "building_context",
    "generating",
    "validating",
    "verifying",
    "finalizing",
    "paused",
    "interrupted",
    "cancelling",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
RESUMABLE_STATUSES = frozenset({"paused", "interrupted"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentError(StrictModel):
    error_code: str
    component: str = "research_agent"
    message: str
    retryable: bool = False
    context: dict[str, JsonValue] = Field(default_factory=dict)
    trace_id: str | None = None


class AgentTokenUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ExpectedEvidence(StrictModel):
    evidence_type: Literal["code", "graph", "paper", "config", "alignment"]
    description: str = Field(min_length=1, max_length=500)
    required: bool = True
    minimum_count: int = Field(default=1, ge=1, le=10)


class StepOutputRef(StrictModel):
    step_id: str = Field(min_length=1, max_length=100)
    field: Literal["entity_ids", "chunk_ids", "edge_ids", "evidence_ids"]
    index: int | None = Field(default=None, ge=0)
    selection: Literal["first", "all", "unique"] = "first"
    required: bool = True

    @model_validator(mode="after")
    def validate_selection(self) -> "StepOutputRef":
        if self.index is not None and self.selection in {"all", "unique"}:
            raise ValueError("index cannot be combined with all/unique selection")
        return self


class ArgumentBinding(StrictModel):
    argument_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=100)
    from_step: StepOutputRef


class PlanStep(StrictModel):
    step_id: str = Field(min_length=1, max_length=100)
    ordinal: int = Field(ge=0, lt=6)
    goal: str = Field(min_length=1, max_length=1_000)
    tool_name: ToolName
    literal_arguments: dict[str, JsonValue] = Field(default_factory=dict)
    argument_bindings: list[ArgumentBinding] = Field(default_factory=list, max_length=20)
    dependencies: list[str] = Field(default_factory=list, max_length=6)
    success_criteria: list[str] = Field(min_length=1, max_length=10)
    expected_evidence: list[ExpectedEvidence] = Field(default_factory=list, max_length=10)
    max_results: int = Field(default=10, ge=1, le=30)

    @model_validator(mode="after")
    def validate_argument_names(self) -> "PlanStep":
        bound = [item.argument_name for item in self.argument_bindings]
        if len(bound) != len(set(bound)):
            raise ValueError("argument bindings must use unique argument names")
        overlap = set(self.literal_arguments).intersection(bound)
        if overlap:
            raise ValueError(f"literal and bound arguments overlap: {sorted(overlap)}")
        return self


class ResearchPlan(StrictModel):
    plan_id: str = Field(min_length=1, max_length=128)
    plan_version: str = Field(min_length=1, max_length=32)
    query_type: QueryType
    goal: str = Field(min_length=1, max_length=1_000)
    steps: list[PlanStep] = Field(min_length=1, max_length=6)
    success_criteria: list[str] = Field(min_length=1, max_length=20)
    expected_evidence: list[ExpectedEvidence] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=10)


class StructuredPlanResponse(StrictModel):
    plan: ResearchPlan
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PlanStepRuntime(StrictModel):
    step_id: str
    plan_version: str
    status: Literal["pending", "resolving", "running", "success", "empty", "failed", "skipped"]
    step_execution_id: str | None = None
    observation_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    skip_reason: str | None = None
    error_code: str | None = None


class ToolObservation(StrictModel):
    observation_id: str
    step_id: str
    plan_version: str
    tool_name: ToolName
    resolved_arguments_hash: str
    tool_call_key: str
    step_execution_id: str
    reused: bool = False
    reused_observation_id: str | None = None
    reused_from_plan_version: str | None = None
    status: Literal["success", "empty", "failed", "timeout"]
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    chunk_ids: list[str] = Field(default_factory=list, max_length=100)
    edge_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    summary: str = Field(default="", max_length=2_000)
    result_count: int = Field(default=0, ge=0, le=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    latency_ms: float = Field(default=0.0, ge=0.0)
    error: AgentError | None = None


class EvidenceCriterionResult(StrictModel):
    criterion: str
    satisfied: bool
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class EvidenceAssessment(StrictModel):
    query_type: QueryType
    sufficient: bool
    criteria: list[EvidenceCriterionResult] = Field(default_factory=list)
    covered_entity_ids: list[str] = Field(default_factory=list)
    covered_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    next_action: Literal["resolve_next", "escalate_to_plan", "replan", "build_context", "partial"]
    reason_codes: list[str] = Field(default_factory=list)


class ReplanDecision(StrictModel):
    allowed: bool
    reason_code: Literal[
        "critical_tool_empty",
        "required_evidence_missing",
        "referenced_entity_missing",
        "path_unreachable",
        "recoverable_tool_error",
        "not_allowed",
    ]
    missing_evidence: list[str] = Field(default_factory=list)
    explanation: str = ""


class DraftAnswerClaim(StrictModel):
    claim_id: str
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    important: bool = True


class DraftResearchAnswer(StrictModel):
    answer: str
    claims: list[DraftAnswerClaim] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ValidatedAnswerClaim(DraftAnswerClaim):
    support_status: Literal["supported", "partially_supported", "unsupported"]
    support_reason: str | None = None


class ValidatedResearchAnswer(StrictModel):
    answer: str
    claims: list[ValidatedAnswerClaim] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class AgentResearchAnswer(StrictModel):
    answer: str
    claims: list[ValidatedAnswerClaim] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_only: bool = False


class AgentBudgetSnapshot(StrictModel):
    max_plan_steps: int = 6
    max_tool_calls: int = 10
    max_replan_count: int = 2
    max_tool_failures: int = 3
    max_graph_hops: int = 2
    max_retrieval_results_per_call: int = 30
    max_final_context_items: int = 8
    tool_call_count: int = 0
    tool_reuse_count: int = 0
    replan_count: int = 0
    tool_failure_count: int = 0


class ResearchRunCreateRequest(StrictModel):
    query: str = Field(min_length=1, max_length=8_000)
    index_version_id: str | None = None
    query_type: QueryType | None = None
    answer_enabled: bool = True
    external_text_consent: bool = False
    parent_run_id: str | None = None
    continued_from_run_id: str | None = None
    seed_evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class ResearchRunResumeRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=500)


class ResearchRunView(StrictModel):
    run_id: str
    thread_id: str
    repo_id: str
    index_version_id: str
    status: ResearchRunStatus
    route: ResearchRoute | None = None
    current_plan_id: str | None = None
    current_plan_version: str | None = None
    current_step: PlanStepRuntime | None = None
    observations: list[ToolObservation] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    budget: AgentBudgetSnapshot = Field(default_factory=AgentBudgetSnapshot)
    answer: AgentResearchAnswer | None = None
    stop_reason: str | None = None
    retryable: bool = False
    cancel_requested: bool = False
    resume_count: int = 0
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class ResearchRunAccepted(StrictModel):
    run_id: str
    thread_id: str
    status: ResearchRunStatus
    repo_id: str
    index_version_id: str
    created_at: datetime


class ResearchResponseEnvelope(StrictModel):
    run: ResearchRunView
    context: ContextBundle | None = None


class LiteralArgument(StrictModel):
    kind: Literal["literal"] = "literal"
    argument_name: str
    value: JsonValue


class StepOutputArgument(StrictModel):
    kind: Literal["step_output"] = "step_output"
    argument_name: str
    from_step: StepOutputRef


TypedArgument = Annotated[LiteralArgument | StepOutputArgument, Field(discriminator="kind")]
