from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.retrieval.benchmark import BenchmarkCase, load_benchmark
from backend.app.retrieval.metrics import evaluate_rankings


def evaluate_predictions(cases: list[BenchmarkCase], predictions: dict[str, dict]) -> dict:
    missing = [case.id for case in cases if case.id not in predictions]
    if missing:
        raise ValueError(f"Missing predictions for {len(missing)} case(s): {missing[:5]}")
    return {
        split: _evaluate_split(
            [case for case in cases if split == "all" or case.split == split], predictions
        )
        for split in ("dev", "locked_test", "all")
    }


def _evaluate_split(cases: list[BenchmarkCase], predictions: dict[str, dict]) -> dict:
    selected = [predictions[case.id] for case in cases]
    latencies = [float(item.get("latency_ms", 0.0)) for item in selected]
    metrics = evaluate_rankings(
        [item.get("ranked_chunk_ids", []) for item in selected],
        [set(case.gold_chunk_ids) for case in cases],
        graph_paths=[item.get("graph_paths", []) for item in selected],
        gold_graph_paths=[case.gold_graph_paths for case in cases],
        latencies_ms=latencies,
    )
    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999) - 1))
    return {
        "case_count": len(cases),
        **asdict(metrics),
        "p50_latency_ms": median(latencies) if latencies else 0.0,
        "p95_latency_ms": ordered[p95_index] if ordered else 0.0,
        "fallback_rate": mean(
            1.0 if item.get("fallback_used", False) else 0.0 for item in selected
        ) if selected else 0.0,
    }


def _load_predictions(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {str(row["case_id"]): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("Prediction case_id values must be unique.")
    return by_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate versioned retrieval predictions.")
    parser.add_argument("--benchmark", default="evaluation/retrieval/benchmark_v1.jsonl")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = evaluate_predictions(
        load_benchmark(args.benchmark), _load_predictions(Path(args.predictions))
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
