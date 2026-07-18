import pytest

from backend.app.alignment.calibrator import (
    CalibrationExample,
    MonotonicBinningCalibrator,
    leave_one_pair_out,
)
from backend.app.alignment.candidate_generator import generate_alignment_candidates
from backend.app.alignment.paper_module_extractor import extract_paper_module_profiles
from backend.app.alignment.scorer import build_profile_decision
from backend.app.alignment.verifier import AlignmentVerifierError, validate_verifier_output
from backend.app.alignment.verifier import ProviderAlignmentVerifier
from backend.app.domain.entities import CodeEntity
from backend.app.llm.config import LLMSettings
from backend.app.llm.providers.mock_provider import MockProvider
from backend.app.llm.runtime import create_llm_runtime
from backend.app.schemas.paper import PaperAnalysis, PaperContribution


def _objects():
    profile = extract_paper_module_profiles(
        alignment_run_id="run",
        repo_id="repo",
        index_version_id="idx",
        paper_id="paper",
        paper_analysis=PaperAnalysis(
            paper_provided=True,
            contributions=[PaperContribution(id="C1", title="Encoder", description="Encoder", evidence=["pe"])],
            module_names=["Encoder"],
        ),
    )[0]
    entity = CodeEntity(
        id="entity", repo_id="repo", entity_type="class", path="m.py", name="Encoder",
        qualified_name="Encoder", content_hash="h", evidence_refs=["ce"],
    )
    candidate = generate_alignment_candidates(profile=profile, code_entities=[entity])[0]
    decision = build_profile_decision(profile=profile, candidates=[candidate], scores=[])
    return profile, candidate, decision


def test_calibration_split_is_by_repo_paper_pair():
    examples = [CalibrationExample(pair, score, label) for pair, score, label in [("p1", .1, 0), ("p2", .9, 1), ("p3", .8, 1), ("p4", .2, 0)]]
    folds = leave_one_pair_out(examples)
    assert set(folds) == {"p1", "p2", "p3", "p4"}
    for pair, (train, validation) in folds.items():
        assert all(item.repo_paper_pair_id != pair for item in train)
        assert {item.repo_paper_pair_id for item in validation} == {pair}


def test_out_of_fold_predictions_cover_all_dev_cases():
    examples = [CalibrationExample(f"p{i}", i / 4, i % 2) for i in range(4)]
    folds = leave_one_pair_out(examples)
    covered = sum((validation for _train, validation in folds.values()), [])
    assert sorted(covered, key=lambda item: item.repo_paper_pair_id) == examples


def test_monotonic_calibrator_is_bounded_and_monotonic():
    calibrator = MonotonicBinningCalibrator.fit([
        CalibrationExample("p1", 0.1, 0), CalibrationExample("p2", 0.8, 1)
    ])
    values = [calibrator.predict(item / 10) for item in range(11)]
    assert values == sorted(values)
    assert all(0 <= item <= 1 for item in values)


def test_verifier_cannot_assign_relation_to_unknown_candidate():
    profile, candidate, decision = _objects()
    with pytest.raises(AlignmentVerifierError, match="candidate_not_in_verifier_input"):
        validate_verifier_output(
            profile=profile,
            candidates=[candidate],
            scorer_decision=decision,
            payload={"verdict": "accept", "selections": [{"candidate_id": "unknown", "relation_type": "implements"}]},
            allowed_evidence_ids={"pe", "ce"},
        )


def test_verifier_cannot_invent_evidence():
    profile, candidate, decision = _objects()
    with pytest.raises(AlignmentVerifierError, match="evidence_not_in_verifier_catalog"):
        validate_verifier_output(
            profile=profile,
            candidates=[candidate],
            scorer_decision=decision,
            payload={"verdict": "accept", "selections": [{"candidate_id": candidate.candidate_id, "relation_type": "implements", "evidence_ids": ["invented"]}]},
            allowed_evidence_ids={"pe", "ce"},
        )


def test_provider_verifier_uses_bounded_candidate_and_evidence_catalog(tmp_path):
    profile, candidate, decision = _objects()

    def response(request):
        allowed = request.input_payload["allowed_candidate_ids"]
        return {
            "verdict": "accept",
            "selections": [
                {
                    "candidate_id": allowed[0],
                    "relation_type": "implements",
                    "evidence_ids": ["pe", "ce"],
                    "reason_codes": ["provider_verified"],
                }
            ],
            "uncertainties": [],
        }

    provider = MockProvider(responses={"alignment_verifier": response})
    settings = LLMSettings.from_env("hybrid").model_copy(
        update={"cache_path": str(tmp_path / "llm.sqlite3"), "max_retries": 0}
    )
    verifier = ProviderAlignmentVerifier(create_llm_runtime(settings, [provider]).router)
    verification, selections = verifier.verify(
        profile=profile,
        candidates=[candidate],
        candidate_scores=[],
        scorer_decision=decision,
        entities={
            "entity": CodeEntity(
                id="entity",
                repo_id="repo",
                entity_type="class",
                path="m.py",
                name="Encoder",
                qualified_name="Encoder",
                content_hash="h",
                evidence_refs=["ce"],
            )
        },
    )
    assert verification.status == "success"
    assert verification.provider == "mock"
    assert verification.token_usage["total_tokens"] == 30
    assert [item.candidate_id for item in selections] == [candidate.candidate_id]
    assert provider.calls[0].task_type == "alignment_verifier"
