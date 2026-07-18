from backend.app.alignment.paper_module_extractor import (
    extract_paper_module_profiles,
)
from backend.app.domain.entities import PaperEntity
from backend.app.schemas.paper import PaperAnalysis, PaperContribution


def _analysis(evidence=None):
    return PaperAnalysis(
        paper_provided=True,
        contributions=[
            PaperContribution(
                id="C1",
                title="Attention and Decoder",
                description="We introduce Attention Module (AM) and Decoder Module (DM).",
                evidence=evidence or ["paper:C1:2", "paper:C1:1"],
            )
        ],
        module_names=["Attention Module", "Decoder Module"],
    )


def _extract(analysis=None, entities=None, generation="profile-generation-v1"):
    return extract_paper_module_profiles(
        alignment_run_id="run-1",
        repo_id="repo-1",
        index_version_id="idx-1",
        paper_id="paper-1",
        paper_analysis=analysis or _analysis(),
        paper_entities=entities or [],
        generation_version=generation,
    )


def test_profile_type_is_explicit():
    profiles = _extract()
    assert profiles
    assert {item.profile_type for item in profiles} == {"module"}
    assert {item.granularity for item in profiles} == {"contribution"}


def test_different_modules_in_same_contribution_are_split():
    profiles = _extract()
    assert {item.normalized_name for item in profiles} == {"attention module", "decoder module"}


def test_same_module_from_text_and_figure_is_merged_deterministically():
    entity = PaperEntity(
        id="paper-figure-1",
        paper_id="paper-1",
        entity_type="figure",
        title="Attention Module",
        text="Attention Module",
        content_hash="hash",
        evidence_refs=["figure:1"],
    )
    profiles = _extract(entities=[entity])
    attention = [item for item in profiles if item.normalized_name == "attention module"]
    assert len(attention) == 1
    assert attention[0].profile_type == "module"
    assert "paper-figure-1" in attention[0].paper_entity_ids


def test_profile_id_stable_under_evidence_order_change():
    left = _extract(_analysis(["e2", "e1"]))
    right = _extract(_analysis(["e1", "e2"]))
    assert [item.profile_id for item in left] == [item.profile_id for item in right]


def test_profile_extractor_version_invalidates_profile_generation():
    left = _extract(generation="profile-generation-v1")
    right = _extract(generation="profile-generation-v2")
    assert {item.profile_id for item in left}.isdisjoint({item.profile_id for item in right})


def test_plain_prose_does_not_create_formula_symbols():
    profiles = _extract()
    assert all(not item.formula_symbols for item in profiles)
