from __future__ import annotations

import os
import stat
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.settings.provider_settings import ProviderSettingsService


client = TestClient(app)


def test_provider_settings_get_never_returns_real_api_key(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-live-abcdef123456")

    response = client.get("/settings/providers")

    assert response.status_code == 200
    text = response.text
    assert "sk-live-abcdef123456" not in text
    deepseek = next(item for item in response.json()["providers"] if item["id"] == "deepseek")
    assert deepseek["configured"] is True
    assert deepseek["masked_key"] == "****3456"


def test_provider_settings_revision_conflict_and_masked_key_rejection(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))

    saved = client.put("/settings/providers/qwen", json={"expected_revision": 0, "model": "qwen-max"})
    conflict = client.put("/settings/providers/qwen", json={"expected_revision": 0, "model": "qwen-plus"})
    masked = client.put("/settings/providers/qwen", json={"expected_revision": 1, "api_key": "****abcd"})

    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert conflict.status_code == 409
    assert masked.status_code == 422
    assert "masked_key" in masked.json()["detail"]
    assert stat.S_IMODE(os.stat(tmp_path / "secrets.json").st_mode) == 0o600


def test_provider_settings_field_merge_keeps_environment_key_and_base_url(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("QWEN_API_KEY", "env-qwen-secret")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    response = client.put("/settings/providers/qwen", json={"expected_revision": 0, "model": "qwen-max"})

    assert response.status_code == 200
    values = ProviderSettingsService().runtime_provider_values("qwen")
    public = response.json()
    assert values["api_key"] == "env-qwen-secret"
    assert values["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert values["model"] == "qwen-max"
    assert public["source"]["model"] == "UI"
    assert public["source"]["base_url"] == "Environment"


def test_provider_validate_blocks_localhost_and_does_not_resolve_dns(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek-secret")

    def fail_dns(*_args, **_kwargs):
        raise AssertionError("validate must not resolve DNS")

    monkeypatch.setattr("socket.getaddrinfo", fail_dns)
    official = client.post("/settings/providers/deepseek/validate", json={"base_url": "https://api.deepseek.com"})
    localhost = client.post("/settings/providers/deepseek/validate", json={
        "base_url": "http://localhost:8000",
        "allow_custom_base_url": True,
    })

    assert official.status_code == 200
    assert official.json()["ok"] is True
    assert localhost.status_code == 200
    assert localhost.json()["ok"] is False
    assert "Localhost" in localhost.json()["errors"][0] or "https" in localhost.json()["errors"][0]


def test_provider_validate_requires_api_key_when_enabled(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = client.post("/settings/providers/deepseek/validate", json={
        "enabled": True,
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    })
    disabled = client.post("/settings/providers/deepseek/validate", json={
        "enabled": False,
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    })
    typed_key = client.post("/settings/providers/deepseek/validate", json={
        "enabled": True,
        "api_key": "sk-test-key",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    })

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "API Key" in response.json()["errors"][0]
    assert disabled.json()["ok"] is True
    assert typed_key.json()["ok"] is True
