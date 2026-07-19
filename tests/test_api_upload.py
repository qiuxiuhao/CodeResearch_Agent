from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_legacy_analysis_upload_routes_are_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("CRA_LEGACY_INTERNAL_API_ENABLED", "false")

    with TestClient(app) as client:
        for path in (
            "/analysis/tasks",
            "/analysis/tasks/async",
            "/analysis/tasks/upload",
            "/analysis/tasks/upload/async",
        ):
            response = client.post(path, files={"zip_file": ("project.zip", b"zip-bytes")})
            assert response.status_code == 410, path
            assert response.json()["detail"]["error_code"] == "legacy_api_disabled"
