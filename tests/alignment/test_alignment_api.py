from fastapi.testclient import TestClient

from backend.app.main import app


def test_alignment_routes_are_stable_when_disabled(monkeypatch):
    monkeypatch.setenv("ALIGNMENT_ENABLED", "false")
    with TestClient(app) as client:
        response = client.get(
            "/repositories/repo/alignments",
            params={"index_version_id": "idx", "paper_id": "paper"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == "alignment_disabled"


def test_alignment_cancel_route_is_registered(monkeypatch):
    monkeypatch.setenv("ALIGNMENT_ENABLED", "false")
    with TestClient(app) as client:
        response = client.post("/alignments/runs/run/cancel")
    assert response.status_code == 503
