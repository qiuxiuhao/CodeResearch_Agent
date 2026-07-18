from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from backend.app.observability.recorder import NoopRecorder, TraceRecorder
from backend.app.observability.redaction import HMACHasher, Redactor
from backend.app.observability.sampling import DeterministicSampler
from backend.app.persistence.observability_store import ObservabilityStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Local, network-free v1.8 recorder benchmark")
    parser.add_argument("--iterations", type=int, default=2_000)
    args = parser.parse_args()
    iterations = max(100, args.iterations)
    noop = _measure_noop(NoopRecorder(), iterations)
    with tempfile.TemporaryDirectory(prefix="cra-observability-") as directory:
        store = ObservabilityStore(Path(directory) / "observability.sqlite3")
        recorder = TraceRecorder(
            store,
            sampler=DeterministicSampler(metadata_enabled=True),
            redactor=Redactor(HMACHasher(key_id=None, key=None)),
        )
        recorder.start()
        metadata = _measure_metadata(recorder, iterations)
        recorder.stop()
    print(json.dumps({"iterations": iterations, "noop": noop, "metadata_enqueue": metadata}, indent=2))


def _measure_noop(recorder: NoopRecorder, iterations: int) -> dict[str, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        with recorder.noop_span():
            pass
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return _summary(samples)


def _measure_metadata(recorder: TraceRecorder, iterations: int) -> dict[str, float]:
    samples = []
    benchmark_started = time.perf_counter()
    for _ in range(iterations):
        started = time.perf_counter_ns()
        handle = recorder.start_span(
            operation="benchmark.operation", trace_type="retrieval", component="retrieval",
            parent_context=None, attributes={},
        )
        handle.end()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    recorder.flush(10)
    elapsed = max(time.perf_counter() - benchmark_started, 0.000_001)
    return {
        **_summary(samples),
        "commands_per_second": round((iterations * 5) / elapsed, 2),
    }


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 4),
        "max_ms": round(max(ordered), 4),
    }


if __name__ == "__main__":
    main()
