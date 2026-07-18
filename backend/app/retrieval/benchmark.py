from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from backend.app.retrieval.schemas import QueryType, StrictModel


class BenchmarkCase(StrictModel):
    benchmark_schema_version: Literal["1"] = "1"
    id: str
    repo_id: str
    index_version_id: str
    query: str
    query_type: QueryType
    split: Literal["dev", "locked_test"]
    filters: dict = Field(default_factory=dict)
    gold_entity_ids: list[str] = Field(default_factory=list)
    gold_chunk_ids: list[str] = Field(default_factory=list)
    relevant_edge_types: list[str] = Field(default_factory=list)
    gold_graph_paths: list[list[str]] = Field(default_factory=list)
    expected_unresolved_symbols: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def require_gold(self) -> "BenchmarkCase":
        if not self.gold_entity_ids and not self.gold_chunk_ids:
            raise ValueError("A benchmark case must contain entity or chunk gold IDs.")
        return self


def load_benchmark(path: str | Path) -> list[BenchmarkCase]:
    cases = [
        BenchmarkCase.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    validate_benchmark(cases)
    return cases


def validate_benchmark(cases: list[BenchmarkCase]) -> None:
    if len(cases) != 40:
        raise ValueError("The v1 benchmark must contain exactly 40 cases.")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Benchmark case IDs must be unique.")
    if sum(case.split == "dev" for case in cases) != 30:
        raise ValueError("The benchmark must contain exactly 30 development cases.")
    locked = [case for case in cases if case.split == "locked_test"]
    if len(locked) != 10:
        raise ValueError("The benchmark must contain exactly 10 locked test cases.")
    required_tags = {
        "exact_symbol", "cross_language", "graph_path",
        "repo_version_isolation", "paper_alignment", "unresolved_negative",
    }
    locked_tags = {tag for case in locked for tag in case.tags}
    missing = required_tags - locked_tags
    if missing:
        raise ValueError(f"Locked test set is missing required coverage: {sorted(missing)}")


def load_fixture_manifest(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_gold_against_fixture(cases: list[BenchmarkCase], fixture: dict) -> None:
    entity_ids = set(fixture["entity_ids"])
    chunk_ids = set(fixture["chunk_ids"])
    edge_ids = set(fixture["edge_ids"])
    for case in cases:
        if not set(case.gold_entity_ids) <= entity_ids:
            raise ValueError(f"{case.id} references unknown entity gold IDs.")
        if not set(case.gold_chunk_ids) <= chunk_ids:
            raise ValueError(f"{case.id} references unknown chunk gold IDs.")
        if any(not set(path) <= edge_ids for path in case.gold_graph_paths):
            raise ValueError(f"{case.id} references unknown graph edge IDs.")
