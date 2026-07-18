from backend.app.alignment.benchmark import (
    AlignmentBenchmarkCase,
    AlignmentPrediction,
    GoldSelection,
)
from backend.app.alignment.metrics import evaluate_alignment_predictions


def _case(case_id: str, split: str, *, alignable: bool = True):
    return AlignmentBenchmarkCase(
        dataset_version="alignment-v1",
        case_id=case_id,
        repo_paper_pair_id="pair-dev" if split == "dev" else "pair-test",
        split=split,
        repo_id="repo",
        index_version_id="idx",
        paper_id="paper",
        profile_id=f"profile-{case_id}",
        profile_generation_version="v1",
        profile_type="module",
        granularity="contribution",
        paper_evidence_ids=["paper-evidence"],
        gold_selections=(
            [GoldSelection(code_entity_id="entity", relation_type="implements")]
            if alignable
            else []
        ),
        alignable=alignable,
        required_code_evidence_ids=["code-evidence"] if alignable else [],
        difficulty="easy",
    )


def test_alignment_metrics_report_dev_and_locked_separately():
    cases = [_case("dev-1", "dev"), _case("test-1", "locked_test", alignable=False)]
    predictions = [
        AlignmentPrediction(
            case_id="dev-1",
            ranked_code_entity_ids=["entity"],
            predicted_selections=[GoldSelection(code_entity_id="entity", relation_type="implements")],
            status="accepted",
            candidate_probabilities={"entity": 0.9, "wrong": 0.1},
            paper_evidence_ids=["paper-evidence"],
            code_evidence_ids=["code-evidence"],
            latency_ms=10,
        ),
        AlignmentPrediction(case_id="test-1", status="abstained", latency_ms=20),
    ]
    report = evaluate_alignment_predictions(cases, predictions)
    assert report["dev"]["candidate_recall_at_5"] == 1.0
    assert report["dev"]["exact_set_match"] == 1.0
    assert report["dev"]["relation_selection_micro_f1"] == 1.0
    assert report["locked_test"]["abstention_recall"] == 1.0
    assert report["all"]["coverage"] == 0.5
    assert report["all"]["p95_latency_ms"] == 20
    assert set(report["all"]["pair_metrics"]) == {"pair-dev", "pair-test"}
