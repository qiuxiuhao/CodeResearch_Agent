from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from backend.app.agents.research.schemas import ResearchRoute, ResearchRunStatus, StrictModel, ToolName
from backend.app.retrieval.schemas import QueryType


class AgentBenchmarkCase(StrictModel):
    benchmark_schema_version: Literal["1"] = "1"
    id: str
    split: Literal["dev", "locked_test"]
    repo_id: str = "fixture_repo_v1"
    index_version_id: str = "fixture_index_v1"
    query: str
    query_type: QueryType
    expected_route: ResearchRoute
    required_tools: list[ToolName] = Field(default_factory=list)
    optional_tools: list[ToolName] = Field(default_factory=list)
    forbidden_tools: list[ToolName] = Field(default_factory=list)
    allowed_tool_orders: list[list[ToolName]] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    required_edge_ids: list[str] = Field(default_factory=list)
    max_tool_calls: int = Field(default=10, ge=0, le=10)
    expected_sufficient: bool = True
    expected_terminal_status: ResearchRunStatus
    fault_injection: dict[str, JsonValue] | None = None
    tags: list[str] = Field(default_factory=list)


class AgentBenchmarkOutcome(StrictModel):
    case_id: str
    route: ResearchRoute
    tools: list[ToolName]
    evidence_ids: list[str]
    edge_ids: list[str]
    terminal_status: ResearchRunStatus
    citation_valid: bool
    plan_valid: bool = True
    tool_arguments_valid: bool = True
    invalid_tool_calls: int = Field(default=0, ge=0)
    tool_reuse_count: int = Field(default=0, ge=0)
    direct_escalated_to_planned: bool = False
    replan_count: int = Field(default=0, ge=0)
    budget_exhausted: bool = False
    recovered: bool = False
    evidence_sufficiency_correct: bool = True
    unsupported_claim_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(ge=0)
    token_usage: int = Field(ge=0)
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)


def load_agent_benchmark(path: str | Path) -> list[AgentBenchmarkCase]:
    cases = [
        AgentBenchmarkCase.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("agent_benchmark_duplicate_case_id")
    return cases


def evaluate_agent_benchmark(
    cases: list[AgentBenchmarkCase], outcomes: list[AgentBenchmarkOutcome]
) -> dict[str, float]:
    by_id = {item.case_id: item for item in outcomes}
    rows = [(case, by_id.get(case.id)) for case in cases]
    count = len(rows) or 1
    route_ok = 0
    success = 0
    forbidden_calls = 0
    total_calls = 0
    evidence_coverage = 0.0
    citation_ok = 0
    terminal_ok = 0
    plan_valid = 0
    arguments_valid = 0
    tool_selection_ok = 0
    invalid_tool_calls = 0
    replanned = 0
    budget_exhausted = 0
    recovered = 0
    evidence_assessment_ok = 0
    unsupported_claims = 0
    latency = 0.0
    tokens = 0
    budget_compliant = 0
    direct_escalations = 0
    tool_reuses = 0
    tool_call_counts: list[int] = []
    latencies: list[float] = []
    for case, outcome in rows:
        if outcome is None:
            continue
        route_ok += outcome.route == case.expected_route
        terminal_match = outcome.terminal_status == case.expected_terminal_status
        terminal_ok += terminal_match
        forbidden = set(outcome.tools).intersection(case.forbidden_tools)
        forbidden_calls += len(forbidden)
        total_calls += len(outcome.tools)
        required = set(case.required_evidence_ids) | set(case.required_edge_ids)
        found = set(outcome.evidence_ids) | set(outcome.edge_ids)
        coverage = len(required & found) / len(required) if required else 1.0
        evidence_coverage += coverage
        required_tools_ok = set(case.required_tools).issubset(outcome.tools)
        tool_selection_ok += required_tools_ok
        budget_ok = len(outcome.tools) <= case.max_tool_calls
        budget_compliant += budget_ok and not outcome.budget_exhausted
        direct_escalations += outcome.direct_escalated_to_planned
        tool_reuses += outcome.tool_reuse_count
        tool_call_counts.append(len(outcome.tools))
        latencies.append(outcome.latency_ms)
        citation_ok += outcome.citation_valid
        plan_valid += outcome.plan_valid
        arguments_valid += outcome.tool_arguments_valid
        invalid_tool_calls += outcome.invalid_tool_calls
        replanned += outcome.replan_count > 0
        budget_exhausted += outcome.budget_exhausted
        recovered += outcome.recovered
        evidence_assessment_ok += outcome.evidence_sufficiency_correct
        unsupported_claims += outcome.unsupported_claim_count
        latency += outcome.latency_ms
        tokens += outcome.token_usage
        success += (
            terminal_match and coverage == 1.0 and required_tools_ok and budget_ok
            and not forbidden and outcome.citation_valid and outcome.evidence_sufficiency_correct
        )
    return {
        "task_success_rate": success / count,
        "route_accuracy": route_ok / count,
        "required_evidence_coverage": evidence_coverage / count,
        "forbidden_tool_call_rate": forbidden_calls / max(1, total_calls),
        "citation_validity": citation_ok / count,
        "terminal_state_accuracy": terminal_ok / count,
        "average_tool_calls": total_calls / count,
        "p50_tool_calls": _percentile(tool_call_counts, 0.5),
        "p95_tool_calls": _percentile(tool_call_counts, 0.95),
        "budget_compliance": budget_compliant / count,
        "direct_escalation_rate": direct_escalations / count,
        "tool_reuse_rate": tool_reuses / max(1, total_calls + tool_reuses),
        "plan_validity": plan_valid / count,
        "tool_selection_accuracy": tool_selection_ok / count,
        "tool_argument_validity": arguments_valid / count,
        "invalid_tool_call_rate": invalid_tool_calls / max(1, total_calls + invalid_tool_calls),
        "replan_rate": replanned / count,
        "budget_exhaustion_rate": budget_exhausted / count,
        "recovery_rate": recovered / count,
        "evidence_sufficiency_accuracy": evidence_assessment_ok / count,
        "unsupported_claim_rate": unsupported_claims / max(1, count),
        "average_latency_ms": latency / count,
        "p50_latency_ms": _percentile(latencies, 0.5),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "average_token_usage": tokens / count,
    }


def _percentile(values: list[float | int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]
