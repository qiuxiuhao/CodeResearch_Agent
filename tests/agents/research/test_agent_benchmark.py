from __future__ import annotations

from pathlib import Path
import json

from backend.app.agents.research.benchmark import (
    AgentBenchmarkOutcome,
    evaluate_agent_benchmark,
    load_agent_benchmark,
)


def test_agent_benchmark_has_frozen_30_case_distribution() -> None:
    cases = load_agent_benchmark(Path("evaluation/agent/benchmark_v1.jsonl"))
    assert len(cases) == 30
    assert sum(item.id.startswith("direct-") for item in cases) == 10
    assert sum(item.id.startswith("planned-") for item in cases) == 15
    assert sum(item.expected_terminal_status == "partial" for item in cases) == 5
    assert sum(item.split == "locked_test" for item in cases) == 10
    catalog = json.loads(Path("evaluation/agent/fixture_catalog_v1.json").read_text(encoding="utf-8"))
    evidence = set(catalog["evidence_ids"])
    edges = set(catalog["edge_ids"])
    assert all(set(item.required_evidence_ids) <= evidence for item in cases)
    assert all(set(item.required_edge_ids) <= edges for item in cases)
    assert all(item.repo_id == catalog["repo_id"] for item in cases)
    assert all(item.index_version_id == catalog["index_version_id"] for item in cases)


def test_agent_metrics_prioritize_evidence_terminal_budget_and_citations() -> None:
    case = load_agent_benchmark(Path("evaluation/agent/benchmark_v1.jsonl"))[:1]
    outcome = AgentBenchmarkOutcome(
        case_id=case[0].id, route=case[0].expected_route, tools=case[0].required_tools,
        evidence_ids=case[0].required_evidence_ids, edge_ids=case[0].required_edge_ids,
        terminal_status=case[0].expected_terminal_status, citation_valid=True,
        latency_ms=1, token_usage=0,
    )
    metrics = evaluate_agent_benchmark(case, [outcome])
    assert metrics["task_success_rate"] == 1.0
    assert metrics["required_evidence_coverage"] == 1.0
    assert metrics["citation_validity"] == 1.0
