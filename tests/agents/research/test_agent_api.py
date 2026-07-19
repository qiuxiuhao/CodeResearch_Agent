from __future__ import annotations

from fastapi.testclient import TestClient
import time

from backend.app.main import app
from backend.app.domain.entities import CodeEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.persistence.index_store import IndexArtifacts, StructuredIndexStore
from backend.app.retrieval.api import get_retrieval_service


def test_agent_routes_are_stable_when_feature_disabled(monkeypatch) -> None:
    monkeypatch.delenv("RESEARCH_AGENT_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/repositories/repo/research/agent/runs", json={"query": "where is forward"}
        )
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == "research_agent_disabled"


def test_openapi_hides_legacy_agent_contract_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("RESEARCH_AGENT_ENABLED", raising=False)
    paths = app.openapi()["paths"]
    assert "/repositories/{repo_id}/research/agent/runs" not in paths
    assert "/research/agent/runs/{run_id}/resume" not in paths
    assert "/research/agent/runs/{run_id}/cancel" not in paths
    assert "/api/v2/workspaces/{workspace_id}/projects/{project_id}/jobs" in paths


def test_agent_api_executes_direct_route_with_checkpoint(tmp_path, monkeypatch) -> None:
    index_path = tmp_path / "index.sqlite3"
    store = StructuredIndexStore(index_path)
    lease = store.begin_version(
        repo_id="repo_agent", identity_mode="explicit", repository_key="agent/repo",
        display_name="agent", input_hash="agent-input",
    )
    evidence = EvidenceRef(
        id="ev-agent", source_type="code", entity_id="entity-agent", file_path="model.py",
        start_line=1, end_line=2,
    )
    entity = CodeEntity(
        id="entity-agent", repo_id="repo_agent", entity_type="function", path="model.py",
        name="forward", qualified_name="model.forward", start_line=1, end_line=2,
        source_code="def forward(x):\n    return x", content_hash="hash-agent",
        evidence_refs=["ev-agent"],
    )
    chunk = SymbolChunk(
        id="chunk-agent", repo_id="repo_agent", entity_id="entity-agent", entity_kind="code",
        chunk_type="function", path="model.py", start_line=1, end_line=2,
        text="def forward(x):\n    return x", content_hash="hash-agent", char_count=28,
    )
    store.mark_ready(lease)
    store.activate(lease, IndexArtifacts([], [entity], [], [], [evidence], [chunk]))
    monkeypatch.setenv("RESEARCH_AGENT_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_INDEX_DB_PATH", str(index_path))
    monkeypatch.setenv("RETRIEVAL_FTS_DB_PATH", str(tmp_path / "fts.sqlite3"))
    monkeypatch.setenv("RESEARCH_RUN_DB_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("RESEARCH_CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite3"))
    get_retrieval_service.cache_clear()
    with TestClient(app) as client:
        created = client.post(
            "/repositories/repo_agent/research/agent/runs",
            json={"query": "model.forward", "query_type": "symbol_lookup", "answer_enabled": False},
            headers={"Idempotency-Key": "direct-1"},
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        current = None
        for _ in range(100):
            current = client.get(f"/research/agent/runs/{run_id}")
            if current.json().get("status") in {"completed", "partial", "failed"}:
                break
            time.sleep(0.03)
    assert current.status_code == 200
    assert current.json()["status"] == "completed", current.text
    assert current.json()["evidence_ids"] == ["ev-agent"]
    get_retrieval_service.cache_clear()
