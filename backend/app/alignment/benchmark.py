from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from backend.app.alignment.schemas import AlignmentRelation, StrictModel


class GoldSelection(StrictModel):
    code_entity_id: str
    relation_type: AlignmentRelation


class AlignmentBenchmarkCase(StrictModel):
    benchmark_schema_version: str = "1"
    dataset_version: str
    case_id: str
    repo_paper_pair_id: str
    split: Literal["dev", "locked_test"]
    repo_id: str
    index_version_id: str
    paper_id: str
    profile_id: str
    profile_generation_version: str
    profile_type: str
    granularity: str
    paper_evidence_ids: list[str] = Field(default_factory=list)
    gold_selections: list[GoldSelection] = Field(default_factory=list)
    alignable: bool
    no_implementation_confirmed: bool = False
    acceptable_alternative_sets: list[list[GoldSelection]] = Field(default_factory=list)
    required_code_evidence_ids: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = Field(default_factory=list)


class AlignmentPrediction(StrictModel):
    case_id: str
    ranked_code_entity_ids: list[str] = Field(default_factory=list)
    predicted_selections: list[GoldSelection] = Field(default_factory=list)
    status: Literal["accepted", "abstained", "needs_review", "no_implementation"]
    candidate_probabilities: dict[str, float] = Field(default_factory=dict)
    paper_evidence_ids: list[str] = Field(default_factory=list)
    code_evidence_ids: list[str] = Field(default_factory=list)
    latency_ms: float | None = Field(default=None, ge=0)
    fallback_used: bool = False

    @field_validator("candidate_probabilities")
    @classmethod
    def probabilities_are_bounded(cls, value: dict[str, float]) -> dict[str, float]:
        if any(probability < 0.0 or probability > 1.0 for probability in value.values()):
            raise ValueError("candidate probabilities must be between zero and one")
        return value


def load_alignment_benchmark(path: str | Path) -> list[AlignmentBenchmarkCase]:
    cases: list[AlignmentBenchmarkCase] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            cases.append(AlignmentBenchmarkCase.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"Invalid alignment benchmark line {line_number}: {exc}") from exc
    _validate_splits(cases)
    return cases


def load_alignment_predictions(path: str | Path) -> list[AlignmentPrediction]:
    predictions: list[AlignmentPrediction] = []
    seen: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            item = AlignmentPrediction.model_validate_json(line)
        except Exception as exc:
            raise ValueError(f"Invalid alignment prediction line {line_number}: {exc}") from exc
        if item.case_id in seen:
            raise ValueError(f"Duplicate alignment prediction case_id: {item.case_id}")
        seen.add(item.case_id)
        predictions.append(item)
    return predictions


def _validate_splits(cases: list[AlignmentBenchmarkCase]) -> None:
    seen: set[str] = set()
    pair_split: dict[str, str] = {}
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"Duplicate alignment benchmark case_id: {case.case_id}")
        seen.add(case.case_id)
        existing = pair_split.setdefault(case.repo_paper_pair_id, case.split)
        if existing != case.split:
            raise ValueError("A repo-paper pair cannot cross Dev and Locked Test splits.")
        if case.no_implementation_confirmed and case.gold_selections:
            raise ValueError("Confirmed no-implementation case cannot have gold selections.")
