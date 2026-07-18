from datetime import UTC, datetime

from backend.app.alignment.candidate_generator import generate_alignment_candidates
from backend.app.alignment.feature_extractor import extract_feature_vector
from backend.app.alignment.paper_module_extractor import extract_paper_module_profiles
from backend.app.alignment.scorer import build_profile_decision, score_feature_vector
from backend.app.domain.entities import CodeEntity
from backend.app.schemas.paper import PaperAnalysis, PaperContribution


def _profile():
    analysis = PaperAnalysis(
        paper_provided=True,
        contributions=[
            PaperContribution(
                id="C1",
                title="Attention Module",
                description="Attention Module maps input tensor to output tensor.",
                evidence=["paper-evidence"],
            )
        ],
        module_names=["Attention Module"],
    )
    return extract_paper_module_profiles(
        alignment_run_id="run",
        repo_id="repo",
        index_version_id="idx",
        paper_id="paper",
        paper_analysis=analysis,
    )[0]


def _entity(identifier="entity-attention", name="AttentionModule"):
    return CodeEntity(
        id=identifier,
        repo_id="repo",
        entity_type="class",
        path="model.py",
        name=name,
        qualified_name=name,
        source_code="class AttentionModule: pass",
        content_hash="hash",
        evidence_refs=["code-evidence"],
    )


def test_candidate_sources_are_merged_by_entity():
    profile = _profile()
    candidates = generate_alignment_candidates(
        profile=profile,
        code_entities=[_entity()],
        legacy_entity_ids=["entity-attention"],
    )
    assert len(candidates) == 1
    assert {item.source for item in candidates[0].source_contributions} == {
        "deterministic_rule",
        "legacy_alignment",
    }


def test_name_only_candidate_cannot_receive_full_confidence():
    profile = _profile().model_copy(update={"role": None, "description": ""})
    candidate = generate_alignment_candidates(profile=profile, code_entities=[_entity()])[0]
    vector = extract_feature_vector(profile=profile, candidate=candidate, entity=_entity())
    score = score_feature_vector(vector)
    assert score.coverage_adjusted_score < 1.0
    assert score.available_weight_ratio < 1.0


def test_not_applicable_feature_does_not_reduce_coverage():
    profile = _profile().model_copy(update={"formula_symbols": [], "figure_neighbor_ids": []})
    candidate = generate_alignment_candidates(profile=profile, code_entities=[_entity()])[0]
    vector = extract_feature_vector(profile=profile, candidate=candidate, entity=_entity())
    statuses = {item.feature_name: item.status for item in vector.features}
    assert statuses["formula_variable"] == "not_applicable"
    assert statuses["figure_topology"] == "not_applicable"


def test_low_scores_produce_abstain_not_no_implementation():
    profile = _profile()
    decision = build_profile_decision(profile=profile, candidates=[], scores=[])
    assert decision.status == "abstained"


def test_no_implementation_requires_strong_negative_and_human_review():
    profile = _profile()
    without_review = build_profile_decision(
        profile=profile, candidates=[], scores=[], strong_negative_evidence=True
    )
    confirmed = build_profile_decision(
        profile=profile,
        candidates=[],
        scores=[],
        strong_negative_evidence=True,
        human_confirmed_no_implementation=True,
    )
    assert without_review.status == "abstained"
    assert confirmed.status == "no_implementation"


def test_multiple_profiles_can_select_same_code_entity():
    profile = _profile()
    candidate = generate_alignment_candidates(profile=profile, code_entities=[_entity()])[0]
    vector = extract_feature_vector(profile=profile, candidate=candidate, entity=_entity())
    score = score_feature_vector(vector)
    left = build_profile_decision(
        profile=profile, candidates=[candidate], scores=[score], accept_threshold=0.0, accept_margin=0.0
    )
    other_profile = profile.model_copy(update={"profile_id": "other-profile"})
    other_candidate = candidate.model_copy(update={"profile_id": "other-profile", "candidate_id": "other-candidate"})
    other_score = score.model_copy(update={"profile_id": "other-profile", "candidate_id": "other-candidate"})
    right = build_profile_decision(
        profile=other_profile,
        candidates=[other_candidate],
        scores=[other_score],
        accept_threshold=0.0,
        accept_margin=0.0,
    )
    assert left.selections and right.selections
