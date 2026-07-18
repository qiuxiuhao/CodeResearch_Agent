from __future__ import annotations

from backend.app.retrieval.benchmark import (
    load_benchmark,
    load_fixture_manifest,
    validate_gold_against_fixture,
)


def test_benchmark_has_30_dev_and_10_locked_with_valid_gold() -> None:
    cases = load_benchmark("evaluation/retrieval/benchmark_v1.jsonl")
    fixture = load_fixture_manifest("evaluation/retrieval/fixture_manifest_v1.json")
    validate_gold_against_fixture(cases, fixture)
    assert sum(case.split == "dev" for case in cases) == 30
    assert sum(case.split == "locked_test" for case in cases) == 10
