from __future__ import annotations

from backend.app.llm.prompt_registry import load_registered_prompt
from backend.app.llm.router import ModelRouter
from backend.app.retrieval.schemas import ContextBundle, ResearchAnswer
from backend.app.schemas.llm_explanation import EvidenceItem


class ProviderAnswerGenerator:
    """Generate one structured answer; citation truth is validated downstream."""

    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    def generate(self, *, query: str, context: ContextBundle) -> ResearchAnswer:
        evidence_catalog = [
            EvidenceItem(
                evidence_id=evidence.evidence_id,
                evidence_type=evidence.source_type,
                file_path=evidence.path,
                start_line=evidence.start_line,
                end_line=evidence.end_line,
                fact_summary=(
                    f"Context {item.context_id}: {item.title}; "
                    f"paper={evidence.paper_id or '-'} page={evidence.page_number or '-'}"
                ),
            )
            for item in context.items
            for evidence in item.evidence
        ]
        result = self.router.generate_structured(
            task_type="research_answer",
            context_id=context.query_id,
            system_prompt=load_registered_prompt("research_answer"),
            input_payload={
                "query": query,
                "repo_id": context.repo_id,
                "index_version_id": context.index_version_id,
                "contexts": [item.model_dump(mode="json") for item in context.items],
            },
            response_model=ResearchAnswer,
            evidence_catalog=evidence_catalog,
            prompt_version="1.0",
        )
        if result.value is None:
            codes = [warning.get("code", "llm_failed") for warning in result.warnings]
            raise RuntimeError(f"Research answer generation failed: {','.join(codes)}")
        return ResearchAnswer.model_validate(result.value)
