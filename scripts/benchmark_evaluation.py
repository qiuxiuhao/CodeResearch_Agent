#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from statistics import mean
from time import perf_counter_ns

from backend.app.evaluation.mock_runner import build_synthetic_suite


async def benchmark(iterations: int) -> dict[str, float | int]:
    durations: list[float] = []
    for index in range(iterations):
        suite = build_synthetic_suite(candidate_commit=f"{index + 1:040x}")
        started = perf_counter_ns()
        run = suite.service.prepare_run(suite.request, caller_scope_hash="benchmark")
        completed = await suite.service.process_run(run.run_id)
        if not completed.complete:
            raise RuntimeError("deterministic evaluation benchmark became incomplete")
        durations.append((perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(durations)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "iterations": iterations,
        "mean_ms": mean(durations),
        "p95_ms": ordered[p95_index],
        "network_requests": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the deterministic Evaluation core.")
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 10_000:
        parser.error("iterations must be between 1 and 10000")
    print(json.dumps(asyncio.run(benchmark(args.iterations)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
