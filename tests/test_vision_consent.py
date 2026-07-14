from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_text_and_vision_consents_are_independent(monkeypatch):
    captured = []

    def fake_run(*args, **kwargs):
        captured.append(kwargs)
        return {
            "task_id": "task_test", "output_dir": "/tmp/task_test", "errors": [],
            "text_llm_enabled": kwargs.get("text_llm_enabled", False),
            "vision_vlm_enabled": kwargs.get("vision_vlm_enabled", False),
        }

    monkeypatch.setattr("backend.app.main.run_analysis", fake_run)
    base = {"zip_path": "examples/small_pytorch_project.zip"}

    text_rejected = client.post("/analysis/tasks", json={**base, "text_llm_enabled": True})
    vision_rejected = client.post("/analysis/tasks", json={**base, "vision_vlm_enabled": True})
    assert text_rejected.status_code == 400
    assert "external_text_consent" in text_rejected.json()["detail"]
    assert vision_rejected.status_code == 400
    assert "external_vision_consent" in vision_rejected.json()["detail"]

    rule = client.post("/analysis/tasks", json=base)
    text = client.post("/analysis/tasks", json={
        **base, "text_llm_enabled": True, "external_text_consent": True,
    })
    vision = client.post("/analysis/tasks", json={
        **base, "vision_vlm_enabled": True, "external_vision_consent": True,
    })
    both = client.post("/analysis/tasks", json={
        **base, "text_llm_enabled": True, "external_text_consent": True,
        "vision_vlm_enabled": True, "external_vision_consent": True,
    })
    assert [response.status_code for response in (rule, text, vision, both)] == [200, 200, 200, 200]
    assert captured[-3]["text_llm_enabled"] is True and captured[-3]["vision_vlm_enabled"] is None
    assert captured[-2]["text_llm_enabled"] is None and captured[-2]["vision_vlm_enabled"] is True
    assert captured[-1]["text_llm_enabled"] is True and captured[-1]["vision_vlm_enabled"] is True


def test_legacy_consent_never_grants_vision_consent():
    response = client.post("/analysis/tasks", json={
        "zip_path": "examples/small_pytorch_project.zip",
        "vision_vlm_enabled": True,
        "external_model_consent": True,
    })
    assert response.status_code == 400
    assert "external_vision_consent" in response.json()["detail"]
