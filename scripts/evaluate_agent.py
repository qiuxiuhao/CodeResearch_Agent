from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.agents.research.benchmark import (
    AgentBenchmarkOutcome,
    evaluate_agent_benchmark,
    load_agent_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate deterministic v1.6 Research Agent outcomes.")
    parser.add_argument("outcomes", help="JSONL file containing AgentBenchmarkOutcome rows")
    parser.add_argument(
        "--benchmark", default="evaluation/agent/benchmark_v1.jsonl",
        help="Versioned Agent benchmark JSONL",
    )
    args = parser.parse_args()
    cases = load_agent_benchmark(args.benchmark)
    outcomes = [
        AgentBenchmarkOutcome.model_validate_json(line)
        for line in Path(args.outcomes).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    all_metrics = evaluate_agent_benchmark(cases, outcomes)
    dev_metrics = evaluate_agent_benchmark([item for item in cases if item.split == "dev"], outcomes)
    test_metrics = evaluate_agent_benchmark(
        [item for item in cases if item.split == "locked_test"], outcomes
    )
    print(json.dumps({"all": all_metrics, "dev": dev_metrics, "locked_test": test_metrics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
