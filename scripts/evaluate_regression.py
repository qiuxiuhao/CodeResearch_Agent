#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.app.evaluation.mock_runner import build_synthetic_suite


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deterministic v1.9 regression suite.")
    parser.add_argument("--mode", default="deterministic_fixture", choices=["deterministic_fixture"])
    parser.add_argument("--dataset-version", default="synthetic-regression-v1")
    parser.add_argument("--baseline-binding")
    parser.add_argument("--gate-config")
    parser.add_argument("--output", default="outputs/evaluation-regression.json")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    if args.dataset_version != "synthetic-regression-v1":
        raise SystemExit(
            "The built-in CI runner only accepts synthetic-regression-v1; use the Evaluation API "
            "for registered frozen datasets."
        )
    suite = build_synthetic_suite()
    evaluation_run = suite.service.prepare_run(suite.request, caller_scope_hash="local-ci")
    completed = await suite.service.process_run(evaluation_run.run_id)
    results = suite.store.list_case_results(completed.run_id)
    metrics = suite.store.list_metric_results(completed.run_id)
    report = {
        "schema_version": "1",
        "dataset_version_id": completed.dataset_version_id,
        "subject_id": completed.subject_id,
        "run_id": completed.run_id,
        "status": completed.status,
        "complete": completed.complete,
        "case_counts": completed.case_counts,
        "results": [item.model_dump(mode="json") for item in results],
        "metrics": [item.model_dump(mode="json") for item in metrics],
        "alignment_benchmark_status": "ALIGNMENT_BENCHMARK_PENDING",
        "note": "Synthetic alignment fixtures validate contracts only and are not human quality Gold.",
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": completed.status, "complete": completed.complete, "output": str(target)}))
    return 0 if completed.status == "completed" and completed.complete else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
