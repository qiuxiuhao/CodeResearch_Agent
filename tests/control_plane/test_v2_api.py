from __future__ import annotations

from fastapi.testclient import TestClient
import io
import time
import zipfile

from backend.app.main import app


def test_v2_local_bootstrap_session_workspace_and_project(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRA_BOOTSTRAP_TOKEN", "bootstrap-token-for-test")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    with TestClient(app, base_url="https://testserver") as client:
        health = client.get("/api/v2/health")
        assert health.json() == {"status": "ok", "profile": "local", "api_contract_version": "2"}
        bootstrap = client.post(
            "/api/v2/auth/bootstrap",
            headers={"X-Bootstrap-Token": "bootstrap-token-for-test"},
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        assert bootstrap.status_code == 201
        second = client.post(
            "/api/v2/auth/bootstrap",
            headers={"X-Bootstrap-Token": "bootstrap-token-for-test"},
            json={"username": "other@example.test", "password": "correct horse battery"},
        )
        assert second.status_code == 400
        login = client.post(
            "/api/v2/auth/login",
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        assert login.status_code == 200
        authorization = {"Authorization": f"Bearer {login.json()['access_token']}"}
        workspace = client.post("/api/v2/workspaces", headers=authorization, json={"name": "Team"})
        assert workspace.status_code == 201
        project = client.post(
            f"/api/v2/workspaces/{workspace.json()['workspace_id']}/projects",
            headers=authorization,
            json={"name": "Research"},
        )
        assert project.status_code == 201


def test_csrf_required_for_cookie_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRA_BOOTSTRAP_TOKEN", "bootstrap-token-for-test")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    with TestClient(app, base_url="https://testserver") as client:
        client.post(
            "/api/v2/auth/bootstrap",
            headers={"X-Bootstrap-Token": "bootstrap-token-for-test"},
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        client.post(
            "/api/v2/auth/login",
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        assert client.post("/api/v2/auth/refresh").status_code == 403


def test_v2_local_session_creates_default_scope_without_personal_login(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    with TestClient(app, base_url="https://testserver") as client:
        session = client.post("/api/v2/auth/local-session")
        assert session.status_code == 200, session.text
        body = session.json()
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        workspaces = client.get("/api/v2/workspaces", headers=headers)
        projects = client.get(f"/api/v2/workspaces/{body['workspace_id']}/projects", headers=headers)
    assert body["workspace_id"].startswith("ws_")
    assert body["project_id"].startswith("project_")
    assert workspaces.json()["items"][0]["name"] == "Local Workspace"
    assert projects.json()["items"][0]["name"] == "Default Project"


def test_v2_local_session_is_loopback_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    with TestClient(app, base_url="https://testserver", client=("203.0.113.10", 50000)) as client:
        response = client.post("/api/v2/auth/local-session")
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "local_session_unavailable"


def test_v2_login_short_password_is_auth_failure_not_validation_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRA_BOOTSTRAP_TOKEN", "bootstrap-token-for-short-login")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    with TestClient(app, base_url="https://testserver") as client:
        created = client.post(
            "/api/v2/auth/bootstrap",
            headers={"X-Bootstrap-Token": "bootstrap-token-for-short-login"},
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        assert created.status_code == 201
        login = client.post(
            "/api/v2/auth/login",
            json={"username": "owner@example.test", "password": "short"},
        )
    assert login.status_code == 401
    assert login.json()["detail"]["error_code"] == "authentication_failed"


def test_v2_local_analysis_runs_through_control_plane(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRA_BOOTSTRAP_TOKEN", "bootstrap-token-for-test")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("main.py", "def answer():\n    return 42\n")
    archive.seek(0)
    with TestClient(app, base_url="https://testserver") as client:
        client.post(
            "/api/v2/auth/bootstrap", headers={"X-Bootstrap-Token": "bootstrap-token-for-test"},
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        login = client.post(
            "/api/v2/auth/login",
            json={"username": "owner@example.test", "password": "correct horse battery"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        workspace = client.post("/api/v2/workspaces", headers=headers, json={"name": "Team"}).json()
        project = client.post(
            f"/api/v2/workspaces/{workspace['workspace_id']}/projects",
            headers=headers, json={"name": "Project"},
        ).json()
        base = f"/api/v2/workspaces/{workspace['workspace_id']}/projects/{project['project_id']}"
        artifact = client.post(
            f"{base}/artifacts", headers=headers,
            files={"artifact": ("repository.zip", archive.getvalue(), "application/zip")},
        )
        assert artifact.status_code == 201, artifact.text
        assert artifact.json()["status"] == "available"
        submitted = client.post(
            f"{base}/jobs", headers=headers,
            json={
                "job_type": "analysis", "idempotency_key": "analysis-request-1",
                "payload": {"repository_artifact_id": artifact.json()["artifact_id"]},
            },
        )
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["job_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = client.get(f"{base}/jobs/{job_id}", headers=headers)
            assert job.status_code == 200, job.text
            if job.json()["status"] in {"completed", "failed", "partial", "cancelled", "dead"}:
                break
            time.sleep(0.05)
        assert job.json()["status"] == "completed", job.text
        assert job.json()["result_artifact_ref_ids"]
        result = client.get(f"{base}/analysis-jobs/{job_id}/result", headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["task_id"] == job_id
        other_workspace = client.post(
            "/api/v2/workspaces", headers=headers, json={"name": "Other"},
        ).json()
        other_project = client.post(
            f"/api/v2/workspaces/{other_workspace['workspace_id']}/projects",
            headers=headers, json={"name": "Other Project"},
        ).json()
        foreign = client.get(
            f"/api/v2/workspaces/{other_workspace['workspace_id']}"
            f"/projects/{other_project['project_id']}/analysis-jobs/{job_id}/result",
            headers=headers,
        )
        assert foreign.status_code == 404


def test_v2_local_analysis_export_backup_and_isolated_restore_journey(monkeypatch, tmp_path):
    monkeypatch.setenv("CRA_DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CONTROL_DATABASE_URL", f"sqlite:///{tmp_path / 'control.sqlite3'}")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRA_BOOTSTRAP_TOKEN", "bootstrap-token-for-release-journey")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("model.py", "def forward(value):\n    return value + 1\n")

    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(
            "/api/v2/auth/bootstrap",
            headers={"X-Bootstrap-Token": "bootstrap-token-for-release-journey"},
            json={"username": "release-owner", "password": "correct horse battery"},
        ).status_code == 201
        login = client.post(
            "/api/v2/auth/login",
            json={"username": "release-owner", "password": "correct horse battery"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        workspace_id = client.post(
            "/api/v2/workspaces", headers=headers, json={"name": "Release"},
        ).json()["workspace_id"]
        project_id = client.post(
            f"/api/v2/workspaces/{workspace_id}/projects",
            headers=headers, json={"name": "Journey"},
        ).json()["project_id"]
        base = f"/api/v2/workspaces/{workspace_id}/projects/{project_id}"
        source = client.post(
            f"{base}/artifacts", headers=headers,
            files={"artifact": ("repository.zip", archive.getvalue(), "application/zip")},
        ).json()
        listed = client.get(f"{base}/artifacts", headers=headers)
        assert listed.status_code == 200
        assert [item["artifact_id"] for item in listed.json()["items"]] == [source["artifact_id"]]
        metadata = client.get(f"{base}/artifacts/{source['artifact_id']}", headers=headers)
        assert metadata.status_code == 200
        assert "storage_key" not in source and "storage_key" not in metadata.json()
        downloaded = client.get(
            f"{base}/artifacts/{source['artifact_id']}/content", headers=headers,
        )
        assert downloaded.status_code == 200
        assert downloaded.content == archive.getvalue()
        assert downloaded.headers["x-content-sha256"] == source["content_hash"]

        def run(job_type: str, payload: dict, suffix: str) -> dict:
            response = client.post(
                f"{base}/jobs", headers=headers,
                json={
                    "job_type": job_type,
                    "idempotency_key": f"release-journey-{suffix}",
                    "payload": payload,
                },
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                current = client.get(f"{base}/jobs/{job_id}", headers=headers)
                assert current.status_code == 200, current.text
                result = current.json()
                if result["status"] in {"completed", "failed", "partial", "cancelled", "dead"}:
                    assert result["status"] == "completed", result
                    return result
                time.sleep(0.05)
            raise AssertionError(f"{job_type} did not terminate")

        analysis = run("analysis", {"repository_artifact_id": source["artifact_id"]}, "analysis")
        result_id = analysis["result_artifact_ref_ids"][0]
        exported = run("export", {"artifact_ids": [result_id]}, "export")
        assert exported["result_artifact_ref_ids"]
        before_rejected = client.get(f"{base}/jobs", headers=headers).json()["items"]
        backup = client.post(
            f"{base}/jobs", headers=headers,
            json={"job_type": "backup", "idempotency_key": "release-backup", "payload": {}},
        )
        assert backup.status_code == 409
        assert backup.json()["detail"]["error_code"] == "local_full_backup_unavailable"
        restore = client.post(
            f"{base}/jobs", headers=headers,
            json={"job_type": "restore", "idempotency_key": "release-restore", "payload": {}},
        )
        assert restore.status_code == 409
        assert restore.json()["detail"]["error_code"] == "local_live_restore_unsupported"
        assert client.get(f"{base}/jobs", headers=headers).json()["items"] == before_rejected
