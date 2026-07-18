from __future__ import annotations

from dataclasses import dataclass

from backend.app.agents.research.schemas import (
    AgentResearchAnswer,
    DraftAnswerClaim,
    DraftResearchAnswer,
    ValidatedAnswerClaim,
    ValidatedResearchAnswer,
)
from backend.app.retrieval.schemas import AnswerCitation, ContextBundle
from backend.app.services.research_answer_generator import ProviderAnswerGenerator


class EvidenceFirstAnswerGenerator:
    """Offline-safe default; a Provider adapter may replace it after consent and budget checks."""

    def generate(self, query: str, context: ContextBundle) -> DraftResearchAnswer:
        citations: list[AnswerCitation] = []
        claims: list[DraftAnswerClaim] = []
        lines: list[str] = []
        for index, item in enumerate(context.items, 1):
            item_citations: list[str] = []
            for evidence_index, evidence in enumerate(item.evidence, 1):
                citation_id = f"cite_{index}_{evidence_index}"
                citations.append(AnswerCitation(
                    citation_id=citation_id,
                    context_id=item.context_id,
                    evidence_id=evidence.evidence_id,
                    entity_id=item.entity_id,
                    path=evidence.path,
                    start_line=evidence.start_line,
                    end_line=evidence.end_line,
                    paper_id=evidence.paper_id,
                    page_number=evidence.page_number,
                ))
                item_citations.append(citation_id)
            statement = f"检索到与问题相关的证据：{item.title}。"
            lines.append(statement)
            claims.append(DraftAnswerClaim(
                claim_id=f"claim_{index}", text=statement, citation_ids=item_citations
            ))
        answer = "\n".join(lines) if lines else "当前索引中没有足够证据回答该问题。"
        return DraftResearchAnswer(
            answer=answer,
            claims=claims,
            citations=citations,
            confidence=min(0.9, 0.4 + 0.1 * len(claims)) if claims else 0.0,
        )


class ConsentAwareAnswerGenerator:
    def __init__(
        self,
        provider: ProviderAnswerGenerator | None,
        fallback: EvidenceFirstAnswerGenerator | None = None,
    ) -> None:
        self.provider = provider
        self.fallback = fallback or EvidenceFirstAnswerGenerator()

    def generate(
        self, query: str, context: ContextBundle, *, external_text_consent: bool
    ) -> DraftResearchAnswer:
        if not external_text_consent or self.provider is None:
            return self.fallback.generate(query, context)
        try:
            generated = self.provider.generate(query=query, context=context)
        except Exception:
            return self.fallback.generate(query, context)
        return DraftResearchAnswer(
            answer=generated.answer,
            claims=[DraftAnswerClaim(
                claim_id=item.claim_id,
                text=item.text,
                citation_ids=item.citation_ids,
            ) for item in generated.claims],
            citations=generated.citations,
            confidence=generated.confidence,
        )


@dataclass(frozen=True, slots=True)
class CitationValidationOutcome:
    answer: DraftResearchAnswer
    invalid_citation_ids: list[str]


class AgentCitationValidator:
    def validate(self, draft: DraftResearchAnswer, context: ContextBundle) -> CitationValidationOutcome:
        lookup = {
            (item.context_id, evidence.evidence_id): (item, evidence)
            for item in context.items
            for evidence in item.evidence
        }
        valid: list[AnswerCitation] = []
        valid_ids: set[str] = set()
        invalid: list[str] = []
        for citation in draft.citations:
            found = lookup.get((citation.context_id, citation.evidence_id))
            if found is None or citation.entity_id != found[0].entity_id:
                invalid.append(citation.citation_id)
                continue
            item, evidence = found
            valid.append(AnswerCitation(
                citation_id=citation.citation_id,
                context_id=item.context_id,
                evidence_id=evidence.evidence_id,
                entity_id=item.entity_id,
                path=evidence.path,
                start_line=evidence.start_line,
                end_line=evidence.end_line,
                paper_id=evidence.paper_id,
                page_number=evidence.page_number,
            ))
            valid_ids.add(citation.citation_id)
        claims = [claim.model_copy(update={
            "citation_ids": [item for item in claim.citation_ids if item in valid_ids]
        }) for claim in draft.claims]
        return CitationValidationOutcome(
            draft.model_copy(update={"citations": valid, "claims": claims}), invalid
        )


class ClaimVerifier:
    def verify(self, draft: DraftResearchAnswer) -> ValidatedResearchAnswer:
        claims: list[ValidatedAnswerClaim] = []
        for claim in draft.claims:
            supported = bool(claim.citation_ids)
            claims.append(ValidatedAnswerClaim(
                **claim.model_dump(),
                support_status="supported" if supported else "unsupported",
                support_reason=None if supported else "No valid citation supports this claim.",
            ))
        confidence = draft.confidence if any(item.support_status == "supported" for item in claims) else min(draft.confidence, 0.2)
        return ValidatedResearchAnswer(
            answer=draft.answer,
            claims=claims,
            citations=draft.citations,
            confidence=confidence,
        )


class AnswerFinalizer:
    def finalize(self, validated: ValidatedResearchAnswer) -> AgentResearchAnswer:
        supported = [item for item in validated.claims if item.support_status == "supported"]
        partial = [item for item in validated.claims if item.support_status == "partially_supported"]
        unsupported = [item.text for item in validated.claims if item.support_status == "unsupported"]
        visible = [item.text for item in supported]
        visible.extend(f"证据仅部分支持：{item.text}" for item in partial)
        evidence_only = not visible
        answer = "\n".join(visible) if visible else "现有证据不足，以下仅返回已检索到的证据。"
        return AgentResearchAnswer(
            answer=answer,
            claims=validated.claims,
            citations=validated.citations,
            unsupported_claims=unsupported,
            confidence=min(validated.confidence, 0.2) if evidence_only else validated.confidence,
            evidence_only=evidence_only,
        )
