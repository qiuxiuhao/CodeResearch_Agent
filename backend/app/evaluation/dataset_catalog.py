from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from backend.app.evaluation.schemas import EvaluationCase, EvaluationDatasetVersion
from backend.app.evaluation.stable_ids import stable_hash
from backend.app.evaluation.store_protocol import EvaluationStoreError, EvaluationStoreProtocol


class DatasetCatalog:
    def __init__(self, store: EvaluationStoreProtocol) -> None:
        self.store = store

    def validate_and_freeze(self, version_id: str) -> EvaluationDatasetVersion:
        version = self.store.get_dataset_version(version_id)
        if version.status == "frozen":
            return version
        if version.status not in {"draft", "validating"}:
            raise EvaluationStoreError("dataset_not_freezable", version.status)
        cases = self.store.list_cases(version_id)
        if not cases:
            raise EvaluationStoreError("dataset_has_no_cases", version_id)
        if any(case.adjudication_status in {"pending", "disputed"} for case in cases):
            raise EvaluationStoreError("gold_adjudication_incomplete", version_id)
        human_cases = [case for case in cases if case.source == "human_authored"]
        if any(
            len(set(case.annotator_scope_hashes)) < 2
            or case.adjudication_status not in {"agreed", "adjudicated"}
            for case in human_cases
        ):
            raise EvaluationStoreError("human_gold_double_review_required", version_id)
        split_by_family: dict[str, set[str]] = {}
        for case in cases:
            split_by_family.setdefault(case.stable_case_family_id, set()).add(case.split)
        if any(len(splits) > 1 for splits in split_by_family.values()):
            raise EvaluationStoreError("evaluation_case_split_leakage", version_id)
        split_counts = Counter(case.split for case in cases)
        source_counts = Counter(case.source for case in cases)
        content_hash = stable_hash([case.model_dump(mode="json") for case in cases])
        frozen = version.model_copy(
            update={
                "status": "frozen",
                "case_count": len(cases),
                "split_counts": dict(split_counts),
                "source_counts": dict(source_counts),
                "content_hash": content_hash,
                "gold_hash": stable_hash([case.gold.model_dump(mode="json") for case in cases]),
                "fixture_hash": stable_hash([case.fixture.model_dump(mode="json") for case in cases]),
                "frozen_at": datetime.now(UTC),
            }
        )
        # Store implementations provide a privileged transition for draft -> frozen.
        if hasattr(self.store, "versions"):
            self.store.versions[version_id] = frozen  # type: ignore[attr-defined]
        else:
            self.store.save_dataset_version(frozen)
        return frozen


def load_case_jsonl(path: str | Path) -> list[EvaluationCase]:
    rows: list[EvaluationCase] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            rows.append(EvaluationCase.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"invalid evaluation case at line {number}: {exc}") from exc
    ids = [item.case_id for item in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation_case_id_duplicate")
    return rows


def write_case_jsonl(path: str | Path, cases: list[EvaluationCase]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(json.dumps(case.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )
