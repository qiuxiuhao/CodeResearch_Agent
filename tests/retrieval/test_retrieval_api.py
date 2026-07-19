from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.domain.entities import CodeEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.main import app
from backend.app.persistence.index_store import IndexArtifacts, StructuredIndexStore
from backend.app.retrieval.api import get_retrieval_service


def _index(path) -> None:
    store = StructuredIndexStore(path)
    lease = store.begin_version(
        repo_id="repo_api", identity_mode="explicit", repository_key="api/repo",
        display_name="api", input_hash="api-input",
    )
    evidence = EvidenceRef(
        id="ev-api", source_type="code", entity_id="entity-api", file_path="model.py",
        start_line=1, end_line=2,
    )
    entity = CodeEntity(
        id="entity-api", repo_id="repo_api", entity_type="function", path="model.py",
        name="forward", qualified_name="model.forward", start_line=1, end_line=2,
        source_code="def forward(x):\n    return x", content_hash="hash-api", evidence_refs=["ev-api"],
    )
    chunk = SymbolChunk(
        id="chunk-api", repo_id="repo_api", entity_id="entity-api", entity_kind="code",
        chunk_type="function", path="model.py", start_line=1, end_line=2,
        text="def forward(x):\n    return x", content_hash="hash-api", char_count=28,
    )
    store.mark_ready(lease)
    store.activate(lease, IndexArtifacts([], [entity], [], [], [evidence], [chunk]))


def test_retrieval_routes_are_internal_and_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("RETRIEVAL_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.post("/repositories/repo/retrieval/search", json={"text": "forward"})
        openapi = client.get("/openapi.json").json()
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == "retrieval_disabled"
    assert "/repositories/{repo_id}/retrieval/search" not in openapi["paths"]
    assert "/api/v2/workspaces/{workspace_id}/projects/{project_id}/library/functions" in openapi["paths"]


def test_sparse_search_and_evidence_only_research_api(tmp_path, monkeypatch) -> None:
    index_path = tmp_path / "index.sqlite3"
    _index(index_path)
    monkeypatch.setenv("RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("STRUCTURED_INDEX_DB_PATH", str(index_path))
    monkeypatch.setenv("RETRIEVAL_FTS_DB_PATH", str(tmp_path / "fts.sqlite3"))
    get_retrieval_service.cache_clear()
    with TestClient(app) as client:
        search = client.post(
            "/repositories/repo_api/retrieval/search",
            json={"text": "model.forward", "query_type": "symbol_lookup"},
        )
        research = client.post(
            "/repositories/repo_api/research/query",
            json={"text": "model.forward", "answer_enabled": False},
        )
        no_consent = client.post(
            "/repositories/repo_api/research/query",
            json={"text": "model.forward", "answer_enabled": True},
        )
        config = client.get("/repositories/repo_api/retrieval/config")
    assert search.status_code == 200
    assert search.json()["candidates"][0]["chunk_id"] == "chunk-api"
    assert search.json()["candidates"][0]["evidence"][0]["path"] == "model.py"
    assert research.status_code == 200
    assert research.json()["evidence_only"] is True
    assert research.json()["context"]["items"][0]["evidence"][0]["start_line"] == 1
    assert no_consent.status_code == 200
    assert no_consent.json()["warnings"] == ["external_text_consent_required_evidence_only"]
    assert config.status_code == 200
    assert config.json()["active_index_version_id"]
    get_retrieval_service.cache_clear()
