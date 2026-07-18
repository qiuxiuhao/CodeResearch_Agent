from __future__ import annotations

from backend.app.retrieval.benchmark import BenchmarkCase
from scripts.evaluate_retrieval import evaluate_predictions


def _case(case_id: str, split: str) -> BenchmarkCase:
    return BenchmarkCase(
        id=case_id,
        repo_id="repo",
        index_version_id="idx",
        query="forward",
        query_type="symbol_lookup",
        split=split,
        gold_entity_ids=["entity"],
        gold_chunk_ids=["gold"],
        difficulty="easy",
    )


def test_report_separates_dev_and_locked_test() -> None:
    cases = [_case("dev-case", "dev"), _case("test-case", "locked_test")]
    report = evaluate_predictions(cases, {
        "dev-case": {"ranked_chunk_ids": ["gold"], "latency_ms": 10},
        "test-case": {"ranked_chunk_ids": ["other"], "latency_ms": 20, "fallback_used": True},
    })
    assert report["dev"]["recall_at_1"] == 1.0
    assert report["locked_test"]["recall_at_1"] == 0.0
    assert report["locked_test"]["fallback_rate"] == 1.0
