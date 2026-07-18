from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.observability.access_policy import LocalAdminAccessPolicy
from backend.app.observability.api import router
from backend.app.observability.middleware import ObservabilityMiddleware
from backend.app.observability.schemas import CallerIdentity, TraceFilter, TraceRecord
from backend.app.services.observability_runtime import (
    get_observability_runtime,
    reset_observability_runtime,
)


def test_observability_api_defaults_disabled(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, api_enabled=False)
    with TestClient(app) as client:
        response = client.get("/observability/traces")
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == "observability_api_disabled"
    reset_observability_runtime()


def test_local_admin_can_access_observability(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, api_enabled=True)
    runtime = get_observability_runtime()
    handle = runtime.recorder.start_span(
        operation="retrieval.search", trace_type="retrieval", component="retrieval",
        parent_context=None, attributes={"cra.repo.id": "repo-a"}, repo_id="repo-a",
    )
    with handle:
        handle.event("retrieval.completed", attributes={"cra.candidate.count": 1})
    assert runtime.recorder.flush(2)
    assert runtime.metrics.snapshot()["telemetry.queue.depth"] == 0
    with TestClient(app) as client:
        response = client.get("/observability/traces")
        detail = client.get(f"/observability/traces/{handle.trace_id}")
        metrics = client.get("/observability/metrics/summary")
    assert response.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["trace"]["trace_id"] == handle.trace_id
    assert metrics.status_code == 200
    assert metrics.json()["runtime"]["span.started.retrieval"] >= 1
    reset_observability_runtime()


def test_span_detail_requires_trace_id(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, api_enabled=True)
    with TestClient(app) as client:
        assert client.get("/observability/spans/abc").status_code == 404
    reset_observability_runtime()


def test_caller_scope_hash_alone_does_not_grant_access():
    policy = LocalAdminAccessPolicy()
    caller = CallerIdentity(identity_type="anonymous", subject="header-value")
    trace = TraceRecord(
        trace_id="1" * 32, trace_type="retrieval", root_span_id="2" * 16,
        caller_scope_hash="same-header-hash", status="completed",
        started_at="2026-07-18T00:00:00+00:00", ended_at="2026-07-18T00:00:01+00:00",
    )
    assert policy.can_read_trace(caller, trace) is False
    assert policy.can_list_traces(caller, TraceFilter()) is False


def _app(monkeypatch, tmp_path, *, api_enabled: bool) -> FastAPI:
    reset_observability_runtime()
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_API_ENABLED", "true" if api_enabled else "false")
    monkeypatch.setenv("OBSERVABILITY_DB_PATH", str(tmp_path / "observability.sqlite3"))
    monkeypatch.setenv("OBSERVABILITY_OTLP_ENABLED", "false")
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(router)
    get_observability_runtime().start()
    return app
