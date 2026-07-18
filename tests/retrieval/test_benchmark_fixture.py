from __future__ import annotations

import sqlite3

from backend.app.retrieval.benchmark import load_benchmark
from evaluation.retrieval.build_fixture import build_fixture


def test_benchmark_gold_exists_in_rebuildable_fixture(tmp_path) -> None:
    database = tmp_path / "benchmark.sqlite3"
    versions = build_fixture(database)
    cases = load_benchmark("evaluation/retrieval/benchmark_v1.jsonl")
    expected_versions = {case.index_version_id for case in cases}
    assert expected_versions == {versions["v1"], versions["v2"]}
    with sqlite3.connect(database) as connection:
        for case in cases:
            entities = {
                row[0] for row in connection.execute(
                    "SELECT entity_id FROM code_entities WHERE index_version_id=? UNION "
                    "SELECT entity_id FROM paper_entities WHERE index_version_id=?",
                    (case.index_version_id, case.index_version_id),
                )
            }
            chunks = {
                row[0] for row in connection.execute(
                    "SELECT chunk_id FROM symbol_chunks WHERE index_version_id=?",
                    (case.index_version_id,),
                )
            }
            assert set(case.gold_entity_ids) <= entities
            assert set(case.gold_chunk_ids) <= chunks
