from __future__ import annotations

from dataclasses import asdict, dataclass

from backend.app.agents.research.schemas import AgentBudgetSnapshot


@dataclass(frozen=True, slots=True)
class AgentBudgetLimits:
    max_plan_steps: int = 6
    max_tool_calls: int = 10
    max_replan_count: int = 2
    max_tool_failures: int = 3
    max_graph_hops: int = 2
    max_retrieval_results_per_call: int = 30
    max_final_context_items: int = 8


class AgentBudget:
    def __init__(self, limits: AgentBudgetLimits | None = None) -> None:
        self.limits = limits or AgentBudgetLimits()

    def snapshot(self, state: dict) -> AgentBudgetSnapshot:
        return AgentBudgetSnapshot(
            **asdict(self.limits),
            tool_call_count=int(state.get("tool_call_count", 0)),
            tool_reuse_count=int(state.get("tool_reuse_count", 0)),
            replan_count=int(state.get("replan_count", 0)),
            tool_failure_count=int(state.get("tool_failure_count", 0)),
        )

    def can_call_tool(self, state: dict) -> bool:
        return int(state.get("tool_call_count", 0)) < self.limits.max_tool_calls

    def can_replan(self, state: dict) -> bool:
        return int(state.get("replan_count", 0)) < self.limits.max_replan_count

    def failures_available(self, state: dict) -> bool:
        return int(state.get("tool_failure_count", 0)) < self.limits.max_tool_failures

    def validate_plan_size(self, plan_steps: int) -> None:
        if plan_steps > self.limits.max_plan_steps:
            raise ValueError("plan_step_budget_exceeded")
