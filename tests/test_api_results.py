from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_legacy_analysis_result_routes_are_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("CRA_LEGACY_INTERNAL_API_ENABLED", "false")

    with TestClient(app) as client:
        for path in (
            "/analysis/tasks",
            "/analysis/tasks/task_abc123",
            "/analysis/tasks/task_abc123/report",
            "/analysis/tasks/task_abc123/figures/fig_123/preview",
            "/library/functions",
            "/settings/providers",
            "/observability/traces",
            "/evaluations/runs",
        ):
            response = client.get(path)
            assert response.status_code == 410, path
            assert response.json()["detail"]["error_code"] == "legacy_api_disabled"


def test_openapi_exposes_only_v2_and_health(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("CRA_LEGACY_INTERNAL_API_ENABLED", "false")

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert paths
    assert all(path == "/health" or path.startswith("/api/v2") for path in paths)
