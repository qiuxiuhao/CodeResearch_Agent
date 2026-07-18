from __future__ import annotations

import os

from backend.app.agents.research.context_service import ResearchContextService
from backend.app.agents.research.answer_pipeline import ConsentAwareAnswerGenerator
from backend.app.agents.research.graph import ResearchGraphRuntime, build_research_agent_graph
from backend.app.agents.research.planner import StructuredPlanner
from backend.app.agents.research.plan_validator import PlanValidator
from backend.app.agents.research.budget import AgentBudget
from backend.app.agents.research.tools.default_tools import build_default_tool_registry
from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.persistence.research_run_store import ResearchRunStore
from backend.app.retrieval.retrieval_service import RetrievalService
from backend.app.llm.config import LLMSettings
from backend.app.llm.runtime import create_llm_runtime
from backend.app.services.research_answer_generator import ProviderAnswerGenerator
from backend.app.alignment.read_service import AlignmentReadService
from backend.app.persistence.alignment_store import AlignmentStore


def build_research_graph_factory(
    *,
    retrieval_service: RetrievalService,
    read_store: RetrievalReadStore,
    run_store: ResearchRunStore,
):
    alignment_read_service = None
    if os.getenv("ALIGNMENT_AGENT_INTEGRATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        alignment_read_service = AlignmentReadService(
            AlignmentStore(os.getenv("ALIGNMENT_DB_PATH", "data/paper_code_alignment.sqlite3")),
            deployment_name=os.getenv("ALIGNMENT_AGENT_DEPLOYMENT", "default"),
        )
    registry = build_default_tool_registry(
        retrieval_service, read_store, alignment_read_service=alignment_read_service
    )
    budget = AgentBudget()
    plan_validator = PlanValidator(registry, budget)
    llm_runtime = create_llm_runtime(LLMSettings.from_env(text_llm_enabled=True))
    provider_answer = (
        ProviderAnswerGenerator(llm_runtime.router)
        if llm_runtime.router.has_available_provider
        else None
    )
    runtime = ResearchGraphRuntime(
        registry=registry,
        context_service=ResearchContextService(read_store),
        run_store=run_store,
        planner=StructuredPlanner(llm_runtime.router, validator=plan_validator),
        plan_validator=plan_validator,
        budget=budget,
        answer_generator=ConsentAwareAnswerGenerator(provider_answer),
    )

    def factory(checkpointer):
        return build_research_agent_graph(runtime, checkpointer=checkpointer)

    return factory
