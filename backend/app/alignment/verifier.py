from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError

from backend.app.alignment.schemas import (
    AlignmentCandidate,
    AlignmentCandidateScore,
    AlignmentDecision,
    AlignmentSelection,
    AlignmentSelectionProposal,
    AlignmentVerification,
    PaperModuleProfile,
    StrictModel,
)
from backend.app.alignment.stable_ids import content_hash, selection_id
from backend.app.domain.entities import CodeEntity
from backend.app.llm.prompt_registry import load_registered_prompt
from backend.app.llm.router import ModelRouter
from backend.app.schemas.llm_explanation import EvidenceItem, LLMCallMetadata


VERIFIER_PROMPT_VERSION = "alignment-verifier-v1"


class AlignmentVerifierError(ValueError):
    pass


class AlignmentVerifierResponse(StrictModel):
    selections: list[AlignmentSelectionProposal] = Field(default_factory=list, max_length=10)
    verdict: Literal["accept", "abstain", "needs_review"]
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    metadata: LLMCallMetadata | None = None


class ProviderAlignmentVerifier:
    """Bounded verifier: the provider may select only server-supplied candidates/evidence."""

    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    def profile_provenance(self) -> dict[str, str | None]:
        provider = next((item for item in self.router.providers if item.configured), None)
        return {
            "verifier_provider": provider.name if provider else None,
            "verifier_model": provider.model if provider else None,
            "verifier_revision": None,
            "verifier_prompt_version": VERIFIER_PROMPT_VERSION,
        }

    def verify(
        self,
        *,
        profile: PaperModuleProfile,
        candidates: list[AlignmentCandidate],
        candidate_scores: list[AlignmentCandidateScore],
        scorer_decision: AlignmentDecision,
        entities: dict[str, CodeEntity],
    ) -> tuple[AlignmentVerification, list[AlignmentSelection]]:
        if not self.router.has_available_provider:
            raise AlignmentVerifierError("verifier_unavailable")
        score_by_candidate = {item.candidate_id: item for item in candidate_scores}
        ranked = sorted(
            candidates,
            key=lambda item: (
                -(
                    score_by_candidate[item.candidate_id].calibrated_match_probability or 0.0
                    if item.candidate_id in score_by_candidate
                    else 0.0
                ),
                item.candidate_id,
            ),
        )[:5]
        allowed_evidence_ids = {
            *profile.evidence_ids,
            *(evidence for item in ranked for evidence in item.code_evidence_ids),
        }
        evidence_catalog = [
            EvidenceItem(
                evidence_id=evidence_id,
                evidence_type=("paper_alignment" if evidence_id in profile.evidence_ids else "code_alignment"),
                fact_summary=f"Server-validated alignment evidence {evidence_id}",
            )
            for evidence_id in sorted(allowed_evidence_ids)
        ]
        input_payload = {
            "profile": {
                "profile_id": profile.profile_id,
                "profile_type": profile.profile_type,
                "canonical_name": profile.canonical_name,
                "description": profile.description,
                "role": profile.role,
                "inputs": profile.inputs,
                "outputs": profile.outputs,
                "formula_symbols": profile.formula_symbols,
                "evidence_ids": profile.evidence_ids,
            },
            "allowed_candidate_ids": [item.candidate_id for item in ranked],
            "candidates": [
                _candidate_payload(
                    item,
                    entities.get(item.code_entity_id),
                    score_by_candidate.get(item.candidate_id),
                )
                for item in ranked
            ],
            "evidence_catalog": [item.model_dump(mode="json") for item in evidence_catalog],
        }

        def validate_response(value: AlignmentVerifierResponse) -> None:
            validate_verifier_output(
                profile=profile,
                candidates=ranked,
                candidate_scores=candidate_scores,
                scorer_decision=scorer_decision,
                payload=value.model_dump(mode="json", exclude={"metadata"}),
                allowed_evidence_ids=allowed_evidence_ids,
            )

        result = self.router.generate_structured(
            task_type="alignment_verifier",
            context_id=f"alignment:{profile.alignment_run_id}:{profile.profile_id}",
            system_prompt=load_registered_prompt("alignment_verifier"),
            input_payload=input_payload,
            response_model=AlignmentVerifierResponse,
            evidence_catalog=evidence_catalog,
            prompt_version=VERIFIER_PROMPT_VERSION,
            result_validator=validate_response,
        )
        if result.value is None:
            raise AlignmentVerifierError("verifier_unavailable")
        response = AlignmentVerifierResponse.model_validate(result.value)
        metadata = response.metadata
        payload = response.model_dump(mode="json", exclude={"metadata"})
        payload["token_usage"] = {
            key: value
            for key, value in {
                "input_tokens": metadata.input_tokens if metadata else None,
                "output_tokens": metadata.output_tokens if metadata else None,
                "total_tokens": metadata.total_tokens if metadata else None,
            }.items()
            if value is not None
        }
        return validate_verifier_output(
            profile=profile,
            candidates=ranked,
            candidate_scores=candidate_scores,
            scorer_decision=scorer_decision,
            payload=payload,
            allowed_evidence_ids=allowed_evidence_ids,
            provider=metadata.provider if metadata else None,
            model=metadata.model if metadata else None,
        )


def validate_verifier_output(
    *,
    profile: PaperModuleProfile,
    candidates: list[AlignmentCandidate],
    scorer_decision: AlignmentDecision,
    candidate_scores: list[AlignmentCandidateScore] | None = None,
    payload: dict,
    allowed_evidence_ids: set[str],
    provider: str | None = None,
    model: str | None = None,
    model_revision: str | None = None,
) -> tuple[AlignmentVerification, list[AlignmentSelection]]:
    allowed_candidates = {item.candidate_id: item for item in candidates}
    try:
        proposals = [AlignmentSelectionProposal.model_validate(item) for item in payload.get("selections", [])]
    except ValidationError as exc:
        raise AlignmentVerifierError("invalid_verifier_schema") from exc
    verdict = payload.get("verdict")
    if verdict not in {"accept", "abstain", "needs_review"}:
        raise AlignmentVerifierError("invalid_verifier_verdict")
    seen: set[str] = set()
    selections: list[AlignmentSelection] = []
    scorer_selections = {item.candidate_id: item for item in scorer_decision.selections}
    trusted_scores = {item.candidate_id: item for item in candidate_scores or []}
    for proposal in proposals:
        if proposal.candidate_id not in allowed_candidates:
            raise AlignmentVerifierError("candidate_not_in_verifier_input")
        if proposal.candidate_id in seen:
            raise AlignmentVerifierError("duplicate_candidate_selection")
        if not set(proposal.evidence_ids) <= allowed_evidence_ids:
            raise AlignmentVerifierError("evidence_not_in_verifier_catalog")
        seen.add(proposal.candidate_id)
        trusted_selection = scorer_selections.get(proposal.candidate_id)
        trusted_score = trusted_scores.get(proposal.candidate_id)
        candidate = allowed_candidates[proposal.candidate_id]
        selections.append(
            AlignmentSelection(
                selection_id=selection_id(
                    decision_id_value=scorer_decision.decision_id,
                    candidate_id_value=proposal.candidate_id,
                    relation_type=proposal.relation_type,
                ),
                candidate_id=proposal.candidate_id,
                relation_type=proposal.relation_type,
                raw_score=(
                    trusted_score.coverage_adjusted_score
                    if trusted_score
                    else trusted_selection.raw_score if trusted_selection else None
                ),
                calibrated_match_probability=(
                    trusted_score.calibrated_match_probability
                    if trusted_score
                    else trusted_selection.calibrated_match_probability if trusted_selection else None
                ),
                paper_evidence_ids=profile.evidence_ids,
                code_evidence_ids=candidate.code_evidence_ids,
                reason_codes=proposal.reason_codes,
            )
        )
    if verdict != "accept" and selections:
        raise AlignmentVerifierError("non_accept_verdict_cannot_select_candidates")
    verification = AlignmentVerification(
        verification_id=content_hash(
            {"run": profile.alignment_run_id, "profile": profile.profile_id, "payload": payload}
        ),
        alignment_run_id=profile.alignment_run_id,
        profile_id=profile.profile_id,
        allowed_candidate_ids=sorted(allowed_candidates),
        proposed_selections=proposals,
        verdict=verdict,
        evidence_ids=sorted({item for proposal in proposals for item in proposal.evidence_ids}),
        uncertainties=list(payload.get("uncertainties", [])),
        provider=provider,
        model=model,
        model_revision=model_revision,
        prompt_version=VERIFIER_PROMPT_VERSION,
        status="success",
        token_usage=dict(payload.get("token_usage", {})),
    )
    return verification, selections


def fallback_verification(profile: PaperModuleProfile, candidates: list[AlignmentCandidate]) -> AlignmentVerification:
    return AlignmentVerification(
        verification_id=content_hash({"run": profile.alignment_run_id, "profile": profile.profile_id, "fallback": True}),
        alignment_run_id=profile.alignment_run_id,
        profile_id=profile.profile_id,
        allowed_candidate_ids=[item.candidate_id for item in candidates],
        proposed_selections=[],
        verdict="abstain",
        evidence_ids=[],
        uncertainties=["verifier_unavailable"],
        prompt_version=VERIFIER_PROMPT_VERSION,
        status="fallback",
        token_usage={},
    )


def apply_verifier_decision(
    scorer_decision: AlignmentDecision,
    verification: AlignmentVerification,
    selections: list[AlignmentSelection],
) -> AlignmentDecision:
    if verification.verdict == "accept" and selections:
        status = "accepted"
    elif verification.verdict == "needs_review":
        status = "needs_review"
        selections = []
    else:
        status = "abstained"
        selections = []
    return scorer_decision.model_copy(
        update={
            "status": status,
            "selections": selections,
            "decision_source": "llm_verifier",
            "verifier_id": verification.verification_id,
            "reason_codes": [*scorer_decision.reason_codes, f"verifier_{verification.verdict}"],
        }
    )


def _candidate_payload(
    candidate: AlignmentCandidate,
    entity: CodeEntity | None,
    score: AlignmentCandidateScore | None,
) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "entity": (
            {
                "entity_type": entity.entity_type,
                "path": entity.path,
                "qualified_name": entity.qualified_name,
                "signature": entity.signature,
                "docstring": (entity.docstring or "")[:1000],
                "start_line": entity.start_line,
                "end_line": entity.end_line,
            }
            if entity
            else None
        ),
        "calibrated_match_probability": score.calibrated_match_probability if score else None,
        "feature_contributions": score.feature_contributions if score else {},
        "source_contributions": [
            item.model_dump(mode="json") for item in candidate.source_contributions
        ],
        "code_evidence_ids": candidate.code_evidence_ids,
    }
