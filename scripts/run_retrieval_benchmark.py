from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.retrieval.api import get_retrieval_service
from backend.app.retrieval.benchmark import load_benchmark
from backend.app.retrieval.retrieval_service import RetrievalExecutionOverrides
from backend.app.retrieval.schemas import RetrievalSearchRequest
from evaluation.retrieval.build_fixture import build_fixture
from scripts.evaluate_retrieval import evaluate_predictions


ABLATIONS = {
    "sparse_only": RetrievalExecutionOverrides(False, True, False, False),
    "dense_only": RetrievalExecutionOverrides(True, False, False, False),
    "dense_sparse": RetrievalExecutionOverrides(True, True, False, False),
    "dense_sparse_graph": RetrievalExecutionOverrides(True, True, True, False),
    "full_reranker": RetrievalExecutionOverrides(True, True, True, True),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one deterministic retrieval ablation.")
    parser.add_argument("--mode", choices=sorted(ABLATIONS), required=True)
    parser.add_argument("--benchmark", default="evaluation/retrieval/benchmark_v1.jsonl")
    parser.add_argument("--index-db", required=True)
    parser.add_argument("--fts-db", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--build-fixture", action="store_true")
    args = parser.parse_args()

    index_path = Path(args.index_db)
    if args.build_fixture:
        if index_path.exists():
            raise SystemExit(f"Refusing to overwrite existing fixture: {index_path}")
        build_fixture(index_path)
    os.environ["STRUCTURED_INDEX_DB_PATH"] = str(index_path)
    os.environ["RETRIEVAL_FTS_DB_PATH"] = str(Path(args.fts_db))
    get_retrieval_service.cache_clear()
    service = get_retrieval_service()
    cases = load_benchmark(args.benchmark)
    execution = ABLATIONS[args.mode]
    rows = []
    for case in cases:
        result = service.search(
            case.repo_id,
            RetrievalSearchRequest(
                text=case.query,
                index_version_id=case.index_version_id,
                query_type=case.query_type,
                filters=case.filters,
                top_k=10,
                include_graph=execution.graph_enabled,
                include_reranker=execution.reranker_enabled,
            ),
            execution=execution,
        )
        rows.append({
            "case_id": case.id,
            "ranked_chunk_ids": [item.chunk_id for item in result.candidates],
            "graph_paths": [
                item.graph_path_edge_ids for item in result.candidates if item.graph_path_edge_ids
            ],
            "latency_ms": result.latency_ms.get("total", 0.0),
            "fallback_used": any("fallback" in warning for warning in result.warnings),
            "warnings": result.warnings,
        })
    predictions = Path(args.predictions)
    report_path = Path(args.report)
    predictions.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    by_id = {row["case_id"]: row for row in rows}
    report = {
        "mode": args.mode,
        "benchmark": args.benchmark,
        "results": evaluate_predictions(cases, by_id),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
