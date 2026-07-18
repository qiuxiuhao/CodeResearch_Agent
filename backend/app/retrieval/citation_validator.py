from __future__ import annotations

from dataclasses import dataclass

from backend.app.retrieval.schemas import (
    AnswerCitation,
    AnswerClaim,
    ContextBundle,
    ResearchAnswer,
)


@dataclass(frozen=True, slots=True)
class CitationValidationResult:
    answer: ResearchAnswer
    evidence_only: bool
    warnings: list[str]


class CitationValidator:
    def validate(self, generated: ResearchAnswer, context: ContextBundle) -> CitationValidationResult:
        evidence_lookup = {
            (item.context_id, evidence.evidence_id): (item, evidence)
            for item in context.items
            for evidence in item.evidence
        }
        valid_citations: list[AnswerCitation] = []
        valid_ids: set[str] = set()
        for citation in generated.citations:
            found = evidence_lookup.get((citation.context_id, citation.evidence_id))
            if found is None:
                continue
            item, evidence = found
            if citation.entity_id != item.entity_id:
                continue
            valid = AnswerCitation(
                citation_id=citation.citation_id,
                context_id=item.context_id,
                evidence_id=evidence.evidence_id,
                entity_id=item.entity_id,
                path=evidence.path,
                start_line=evidence.start_line,
                end_line=evidence.end_line,
                paper_id=evidence.paper_id,
                page_number=evidence.page_number,
            )
            valid_citations.append(valid)
            valid_ids.add(valid.citation_id)
        claims: list[AnswerClaim] = []
        unsupported = list(generated.unsupported_claims)
        for claim in generated.claims:
            citation_ids = [citation_id for citation_id in claim.citation_ids if citation_id in valid_ids]
            supported = bool(citation_ids)
            if not supported and claim.text not in unsupported:
                unsupported.append(claim.text)
            claims.append(claim.model_copy(update={"citation_ids": citation_ids, "supported": supported}))
        evidence_only = bool(claims) and not any(claim.supported for claim in claims)
        confidence = min(generated.confidence, 0.25) if evidence_only else generated.confidence
        warnings = ["invalid_citations_removed"] if len(valid_citations) != len(generated.citations) else []
        if evidence_only:
            warnings.append("all_claims_unsupported_evidence_only")
        return CitationValidationResult(
            answer=generated.model_copy(update={
                "claims": claims,
                "citations": valid_citations,
                "unsupported_claims": unsupported,
                "confidence": confidence,
            }),
            evidence_only=evidence_only,
            warnings=warnings,
        )
