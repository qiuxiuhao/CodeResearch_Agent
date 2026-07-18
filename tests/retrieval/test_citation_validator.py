from __future__ import annotations

from backend.app.retrieval.citation_validator import CitationValidator
from backend.app.retrieval.schemas import (
    AnswerCitation,
    AnswerClaim,
    ContextBundle,
    ContextItem,
    ResearchAnswer,
    RetrievalEvidence,
)


def _context() -> ContextBundle:
    return ContextBundle(
        repo_id="repo", index_version_id="idx", query_id="query",
        items=[ContextItem(
            context_id="ctx-1", entity_id="entity-1", chunk_ids=["chunk-1"], title="forward",
            text="def forward(): pass", token_count=5, truncated=False, rank=1,
            evidence=[RetrievalEvidence(
                evidence_id="ev-1", source_type="code", path="model.py", start_line=10, end_line=12,
            )],
        )],
        estimated_tokens=5, token_count_method="conservative_code_estimate", token_budget=100,
    )


def _answer(citation: AnswerCitation) -> ResearchAnswer:
    return ResearchAnswer(
        answer="forward is implemented here.",
        claims=[AnswerClaim(claim_id="claim-1", text="implemented", citation_ids=[citation.citation_id], supported=True)],
        citations=[citation], confidence=0.9,
    )


def test_generated_citation_must_exist_in_context() -> None:
    generated = _answer(AnswerCitation(
        citation_id="cite-1", context_id="missing", evidence_id="ev-1", entity_id="entity-1"
    ))
    result = CitationValidator().validate(generated, _context())
    assert not result.answer.citations
    assert not result.answer.claims[0].supported


def test_model_cannot_change_evidence_line_range() -> None:
    generated = _answer(AnswerCitation(
        citation_id="cite-1", context_id="ctx-1", evidence_id="ev-1", entity_id="entity-1",
        path="fake.py", start_line=999, end_line=1000,
    ))
    citation = CitationValidator().validate(generated, _context()).answer.citations[0]
    assert (citation.path, citation.start_line, citation.end_line) == ("model.py", 10, 12)


def test_unsupported_claim_is_exposed() -> None:
    generated = _answer(AnswerCitation(
        citation_id="cite-1", context_id="ctx-1", evidence_id="missing", entity_id="entity-1"
    ))
    result = CitationValidator().validate(generated, _context())
    assert result.answer.unsupported_claims == ["implemented"]


def test_all_invalid_citations_fall_back_to_evidence_only() -> None:
    generated = _answer(AnswerCitation(
        citation_id="cite-1", context_id="ctx-1", evidence_id="missing", entity_id="entity-1"
    ))
    result = CitationValidator().validate(generated, _context())
    assert result.evidence_only
    assert result.answer.confidence == 0.25
    assert "all_claims_unsupported_evidence_only" in result.warnings
