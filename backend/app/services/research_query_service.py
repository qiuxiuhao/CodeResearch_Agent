from __future__ import annotations

from typing import Protocol

from backend.app.retrieval.citation_validator import CitationValidator
from backend.app.retrieval.retrieval_service import RetrievalService
from backend.app.retrieval.schemas import (
    ContextBundle,
    ResearchAnswer,
    ResearchQueryRequest,
    ResearchResponse,
    RetrievalSearchRequest,
)


class AnswerGenerator(Protocol):
    def generate(self, *, query: str, context: ContextBundle) -> ResearchAnswer: ...


class ResearchQueryService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        *,
        answer_generator: AnswerGenerator | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.answer_generator = answer_generator
        self.citation_validator = CitationValidator()

    def query(self, repo_id: str, request: ResearchQueryRequest) -> ResearchResponse:
        search_request = RetrievalSearchRequest.model_validate(
            request.model_dump(exclude={"answer_enabled", "external_text_consent"})
        )
        retrieval = self.retrieval_service.search(repo_id, search_request)
        notes: dict[str, list[str]] = {}
        context = self.retrieval_service.context_builder.build(
            repo_id=repo_id,
            index_version_id=retrieval.active_index_version_id,
            query_id=retrieval.query.query_id,
            query_text=request.text,
            candidates=retrieval.candidates,
            token_budget=retrieval.effective_config.token_budget,
            max_entities=retrieval.effective_config.max_entities,
            relationship_notes=notes,
        )
        if not request.answer_enabled:
            return ResearchResponse(
                retrieval=retrieval,
                context=context,
                answer=None,
                evidence_only=True,
                warnings=["answer_disabled_evidence_only"],
            )
        if not request.external_text_consent:
            return ResearchResponse(
                retrieval=retrieval,
                context=context,
                answer=None,
                evidence_only=True,
                warnings=["external_text_consent_required_evidence_only"],
            )
        if self.answer_generator is None:
            return ResearchResponse(
                retrieval=retrieval,
                context=context,
                answer=None,
                evidence_only=True,
                warnings=["answer_generator_unavailable_evidence_only"],
            )
        try:
            generated = self.answer_generator.generate(query=request.text, context=context)
        except Exception:
            return ResearchResponse(
                retrieval=retrieval,
                context=context,
                answer=None,
                evidence_only=True,
                warnings=["answer_generation_failed_evidence_only"],
            )
        validated = self.citation_validator.validate(generated, context)
        return ResearchResponse(
            retrieval=retrieval,
            context=context,
            answer=validated.answer,
            evidence_only=validated.evidence_only,
            warnings=validated.warnings,
        )
