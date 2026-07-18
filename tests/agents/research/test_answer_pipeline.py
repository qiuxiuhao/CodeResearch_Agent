from __future__ import annotations

from backend.app.agents.research.answer_pipeline import AgentCitationValidator, AnswerFinalizer, ClaimVerifier
from backend.app.agents.research.schemas import DraftAnswerClaim, DraftResearchAnswer
from backend.app.retrieval.schemas import AnswerCitation, ContextBundle, ContextItem, RetrievalEvidence


def _context() -> ContextBundle:
    return ContextBundle(
        repo_id="repo", index_version_id="v1", query_id="q",
        items=[ContextItem(
            context_id="ctx", entity_id="ent", chunk_ids=["chunk"], title="symbol", text="source",
            token_count=1, truncated=False, rank=1,
            evidence=[RetrievalEvidence(
                evidence_id="ev", source_type="code", path="real.py", start_line=1, end_line=2
            )],
        )], estimated_tokens=1, token_count_method="conservative_code_estimate", token_budget=10,
    )


def test_citations_are_validated_before_claims_and_line_changes_are_rejected() -> None:
    draft = DraftResearchAnswer(
        answer="claim", claims=[DraftAnswerClaim(claim_id="c", text="claim", citation_ids=["cite"])],
        citations=[AnswerCitation(
            citation_id="cite", context_id="ctx", evidence_id="ev", entity_id="ent",
            path="invented.py", start_line=999, end_line=999,
        )], confidence=0.9,
    )
    citation_checked = AgentCitationValidator().validate(draft, _context()).answer
    assert citation_checked.citations[0].path == "real.py"
    assert citation_checked.citations[0].start_line == 1
    verified = ClaimVerifier().verify(citation_checked)
    assert verified.claims[0].support_status == "supported"


def test_unsupported_claim_removed_from_visible_answer() -> None:
    draft = DraftResearchAnswer(
        answer="unsupported certainty",
        claims=[DraftAnswerClaim(claim_id="c", text="unsupported certainty", citation_ids=[])],
        confidence=0.9,
    )
    final = AnswerFinalizer().finalize(ClaimVerifier().verify(draft))
    assert "unsupported certainty" not in final.answer
    assert final.unsupported_claims == ["unsupported certainty"]
    assert final.evidence_only is True
