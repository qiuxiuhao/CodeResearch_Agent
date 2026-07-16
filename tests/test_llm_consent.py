from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.analysis_service import run_analysis


def test_hybrid_requires_backend_consent(tmp_path):
    with TestClient(app) as client:
        response = client.post("/analysis/tasks", json={
            "zip_path": "examples/small_pytorch_project.zip",
            "output_root": str(tmp_path),
            "analysis_mode": "hybrid",
            "external_model_consent": False,
        })
    assert response.status_code == 400
    assert "external_model_consent" in response.json()["detail"]
    assert not list(tmp_path.glob("task_*"))


def test_service_rejects_hybrid_without_consent(tmp_path):
    try:
        run_analysis("examples/small_pytorch_project.zip", tmp_path, analysis_mode="hybrid")
    except ValueError as exc:
        assert "external_model_consent" in str(exc)
    else:
        raise AssertionError("hybrid mode must require consent")


def test_public_config_exposes_only_safe_limits():
    with TestClient(app) as client:
        response = client.get("/llm/public-config")
    assert response.status_code == 200
    body = response.json()
    assert body["default_analysis_mode"] in {"rule", "hybrid"}
    assert "max_total_entities" in body
    assert "max_provider_requests" in body
    assert body["image_generation"]["teaching_narrative_max_provider_requests"] >= 0
    assert body["image_generation"]["teaching_review_max_provider_requests"] >= 0
    assert "api_key" not in str(body).lower()
