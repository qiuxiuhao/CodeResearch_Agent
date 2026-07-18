from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from backend.app.agents.research.schemas import (
    AgentError,
    AgentResearchAnswer,
    AgentTokenUsage,
    DraftResearchAnswer,
    EvidenceAssessment,
    PlanStepRuntime,
    ResearchPlan,
    ResearchRoute,
    ResearchRunStatus,
    ToolObservation,
    ValidatedResearchAnswer,
)
from backend.app.retrieval.schemas import ContextBundle, QueryType


class ResearchState(TypedDict, total=False):
    state_schema_version: str
    graph_version: str
    run_id: str
    thread_id: str
    parent_run_id: str | None
    continued_from_run_id: str | None
    repo_id: str
    index_version_id: str
    query: str
    query_type: QueryType
    route: ResearchRoute
    route_reason: list[str]
    direct_escalated_to_planned: bool
    plan: ResearchPlan | None
    pending_plan: ResearchPlan | None
    plan_history_ids: list[str]
    current_step_index: int
    step_runtime: list[PlanStepRuntime]
    resolved_arguments: dict[str, object]
    step_resolution_failed: bool
    observations: list[ToolObservation]
    evidence_ids: list[str]
    seed_evidence_ids: list[str]
    entity_ids: list[str]
    evidence_assessment: EvidenceAssessment | None
    evidence_sufficient: bool
    missing_evidence: list[str]
    context: ContextBundle | None
    draft_answer: DraftResearchAnswer | None
    validated_answer: ValidatedResearchAnswer | None
    answer: AgentResearchAnswer | None
    confidence: float
    answer_enabled: bool
    external_text_consent: bool
    tool_call_count: int
    tool_reuse_count: int
    replan_count: int
    tool_failure_count: int
    token_usage: AgentTokenUsage
    status: ResearchRunStatus
    previous_status: ResearchRunStatus | None
    stop_reason: str | None
    errors: list[AgentError]
    cancel_requested: bool
    resume_count: int
    last_resumed_at: datetime | None
    created_at: datetime
    updated_at: datetime
