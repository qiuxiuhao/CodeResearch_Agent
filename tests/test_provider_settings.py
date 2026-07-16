from __future__ import annotations

import os
import stat
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.llm.config import LLMSettings
from backend.app.settings.provider_settings import ProviderSettingsService
from backend.app.services.analysis_service import run_analysis
from backend.app.vision.config import VisionSettings


def test_provider_settings_get_never_returns_real_api_key(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-live-abcdef123456")

    with TestClient(app) as client:
        response = client.get("/settings/providers")

    assert response.status_code == 200
    text = response.text
    assert "sk-live-abcdef123456" not in text
    deepseek = next(item for item in response.json()["providers"] if item["id"] == "deepseek")
    assert deepseek["configured"] is True
    assert deepseek["masked_key"] == "****3456"
    assert deepseek["api_key_source"] == "Environment"


def test_provider_settings_revision_conflict_and_masked_key_rejection(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))

    with TestClient(app) as client:
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

    with TestClient(app) as client:
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
    with TestClient(app) as client:
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

    with TestClient(app) as client:
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


def test_provider_settings_ui_fields_override_runtime_env_per_provider(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("VLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("VLM_MAX_RETRIES", "1")
    monkeypatch.setenv("VLM_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("IMAGE_GENERATION_MAX_RETRIES", "0")

    with TestClient(app) as client:
        deepseek = client.put("/settings/providers/deepseek", json={
            "expected_revision": 0,
            "api_key": "ui-deepseek-key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "timeout_seconds": 111,
            "retry": 4,
            "max_output_tokens": 1100,
        })
        assert deepseek.status_code == 200
        text = client.put("/settings/providers/qwen", json={
            "expected_revision": deepseek.json()["revision"],
            "api_key": "ui-qwen-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-max",
            "timeout_seconds": 33,
            "retry": 1,
            "max_output_tokens": 333,
        })
        assert text.status_code == 200
        vision = client.put("/settings/providers/qwen_vl", json={
            "expected_revision": text.json()["revision"],
            "api_key": "ui-vl-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-vl-max",
            "timeout_seconds": 44,
            "retry": 4,
            "max_output_tokens": 444,
            "supports_json_object": True,
            "disable_thinking": True,
        })
        assert vision.status_code == 200
        glm = client.put("/settings/providers/glm_v", json={
            "expected_revision": vision.json()["revision"],
            "api_key": "ui-glm-key",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4.5v",
            "timeout_seconds": 55,
            "retry": 2,
            "max_output_tokens": 555,
        })
        assert glm.status_code == 200
        image = client.put("/settings/providers/qwen_image", json={
            "expected_revision": glm.json()["revision"],
            "api_key": "ui-image-key",
            "base_url": "https://dashscope.aliyuncs.com",
            "model": "qwen-image",
            "timeout_seconds": 14,
            "retry": 2,
            "request_width": 1024,
            "request_height": 768,
        })
        assert image.status_code == 200
        seedream = client.put("/settings/providers/seedream", json={
            "expected_revision": image.json()["revision"],
            "api_key": "ui-seedream-key",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "seedream",
            "timeout_seconds": 15,
            "retry": 3,
            "request_width": 1024,
            "request_height": 768,
        })
        assert seedream.status_code == 200

    llm = LLMSettings.from_env(text_llm_enabled=True)
    vision_settings = VisionSettings.from_env(True)
    image_settings = ImageGenerationSettings.from_env(True, external_image_consent=True)

    assert llm.timeout_seconds == 45
    assert llm.max_retries == 1
    assert llm.max_output_tokens == 1200
    assert llm.deepseek.timeout_seconds == 111
    assert llm.deepseek.max_retries == 4
    assert llm.deepseek.max_output_tokens == 1100
    assert llm.qwen.timeout_seconds == 33
    assert llm.qwen.max_retries == 1
    assert llm.qwen.max_output_tokens == 333
    assert vision_settings.timeout_seconds == 45
    assert vision_settings.max_retries == 1
    assert vision_settings.max_output_tokens == 1200
    assert vision_settings.qwen_vl.timeout_seconds == 44
    assert vision_settings.qwen_vl.max_retries == 4
    assert vision_settings.qwen_vl.max_output_tokens == 444
    assert vision_settings.glm_v.timeout_seconds == 55
    assert vision_settings.glm_v.max_retries == 2
    assert vision_settings.glm_v.max_output_tokens == 555
    assert vision_settings.qwen_vl.supports_json_object is True
    assert vision_settings.qwen_vl.disable_thinking is True
    assert image_settings.timeout_seconds == 60
    assert image_settings.max_retries == 0
    assert image_settings.qwen_image.timeout_seconds == 14
    assert image_settings.qwen_image.max_retries == 2
    assert image_settings.seedream.timeout_seconds == 15
    assert image_settings.seedream.max_retries == 3


def test_provider_settings_rejects_async_image_mode(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))

    with TestClient(app) as client:
        validate = client.post("/settings/providers/qwen_image/validate", json={
            "api_key": "key",
            "base_url": "https://dashscope.aliyuncs.com",
            "model": "qwen-image",
            "supports_async": True,
        })
        save = client.put("/settings/providers/qwen_image", json={
            "expected_revision": 0,
            "api_key": "key",
            "base_url": "https://dashscope.aliyuncs.com",
            "model": "qwen-image",
            "supports_async": True,
        })

    assert validate.status_code == 422
    assert "supports_async" in validate.json()["detail"]
    assert save.status_code == 422
    assert "supports_async" in save.json()["detail"]


def test_provider_settings_accepts_false_async_compat_without_persisting(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "secrets.json"
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(store_path))

    with TestClient(app) as client:
        saved = client.put("/settings/providers/qwen_image", json={
            "expected_revision": 0,
            "supports_async": False,
        })

    assert saved.status_code == 200
    assert "supports_async" not in saved.json()["fields"]
    assert "supports_async" not in store_path.read_text(encoding="utf-8")


def test_legacy_secret_store_async_value_is_ignored(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "secrets.json"
    store_path.write_text(
        '{"schema_version":1,"revision":4,"providers":{"qwen_image":{"config":{"supports_async":true}}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(store_path))

    with TestClient(app) as client:
        public = client.get("/settings/providers").json()

    image = next(item for item in public["providers"] if item["id"] == "qwen_image")
    assert "supports_async" not in image["fields"]


def test_provider_settings_rejects_empty_allowed_domains(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))

    with TestClient(app) as client:
        validate = client.post("/settings/providers/qwen_image/validate", json={
            "api_key": "key",
            "base_url": "https://dashscope.aliyuncs.com",
            "model": "qwen-image",
            "allowed_domains": [],
        })
        save = client.put("/settings/providers/qwen_image", json={
            "expected_revision": 0,
            "api_key": "key",
            "base_url": "https://dashscope.aliyuncs.com",
            "model": "qwen-image",
            "allowed_domains": [],
        })

    assert validate.status_code == 200
    assert validate.json()["ok"] is False
    assert "allowed_domains" in validate.json()["errors"][0]
    assert save.status_code == 422
    assert "allowed_domains" in save.json()["detail"]


def test_corrupt_secret_store_is_not_overwritten_and_env_remains_readonly(monkeypatch, tmp_path: Path):
    store_path = tmp_path / "secrets.json"
    store_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(store_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek-secret")

    with TestClient(app) as client:
        listed = client.get("/settings/providers")
        save = client.put("/settings/providers/deepseek", json={
            "expected_revision": 0,
            "model": "deepseek-chat",
        })

    assert listed.status_code == 200
    assert listed.json()["warnings"]
    deepseek = next(item for item in listed.json()["providers"] if item["id"] == "deepseek")
    assert deepseek["configured"] is True
    assert deepseek["api_key_source"] == "Environment"
    assert save.status_code == 422
    assert "damaged" in save.json()["detail"] or "unreadable" in save.json()["detail"]
    assert store_path.read_text(encoding="utf-8") == "{bad json"
    assert store_path.with_suffix(".json.corrupt").read_text(encoding="utf-8") == "{bad json"


def test_provider_settings_delete_key_clears_ui_key_without_exposing_secret(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with TestClient(app) as client:
        saved = client.put("/settings/providers/deepseek", json={
            "expected_revision": 0,
            "api_key": "sk-ui-secret-123456",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
        })
        assert saved.status_code == 200
        assert saved.json()["api_key_source"] == "UI"
        assert "sk-ui-secret-123456" not in saved.text
        deleted = client.request(
            "DELETE",
            "/settings/providers/deepseek/api-key",
            json={"expected_revision": saved.json()["revision"]},
        )

    assert deleted.status_code == 200
    assert deleted.json()["api_key_source"] == "None"
    assert deleted.json()["configured"] is False


def test_provider_settings_environment_key_is_readonly_on_delete(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-secret")

    with TestClient(app) as client:
        listed = client.get("/settings/providers")
        deepseek = next(item for item in listed.json()["providers"] if item["id"] == "deepseek")
        deleted = client.request(
            "DELETE",
            "/settings/providers/deepseek/api-key",
            json={"expected_revision": deepseek["revision"]},
        )

    assert deepseek["api_key_source"] == "Environment"
    assert deleted.status_code == 422
    assert "Environment" in deleted.json()["detail"]


def test_provider_settings_write_security_checks_remote_origin_and_admin_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    payload = {"expected_revision": 0, "model": "deepseek-chat"}

    with TestClient(app) as client:
        bad_origin = client.put("/settings/providers/deepseek", json=payload, headers={"origin": "https://evil.example"})
        localhost_evil = client.put("/settings/providers/deepseek", json=payload, headers={"origin": "http://localhost.evil.com"})
        loopback_evil = client.put("/settings/providers/deepseek", json=payload, headers={"origin": "http://127.0.0.1.evil.com"})
        allowed_localhost = client.put("/settings/providers/deepseek", json=payload, headers={"origin": "http://localhost:5173"})
    assert bad_origin.status_code == 403
    assert localhost_evil.status_code == 403
    assert loopback_evil.status_code == 403
    assert allowed_localhost.status_code == 200
    remote_payload = {"expected_revision": allowed_localhost.json()["revision"], "model": "deepseek-chat"}

    with TestClient(app, client=("203.0.113.10", 50000)) as remote_client:
        remote_blocked = remote_client.put("/settings/providers/deepseek", json=remote_payload)
    assert remote_blocked.status_code == 403

    monkeypatch.setenv("REMOTE_PROVIDER_SETTINGS_ENABLED", "true")
    monkeypatch.setenv("PROVIDER_SETTINGS_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("PROVIDER_SETTINGS_ALLOWED_ORIGINS", "https://admin.example")
    with TestClient(app, client=("203.0.113.10", 50000)) as remote_client:
        missing_token = remote_client.put("/settings/providers/deepseek", json=remote_payload, headers={"origin": "https://admin.example"})
        allowed = remote_client.put(
            "/settings/providers/deepseek",
            json=remote_payload,
            headers={"origin": "https://admin.example", "x-admin-token": "admin-token"},
        )

    assert missing_token.status_code == 403
    assert allowed.status_code == 200


def test_runtime_blocks_custom_base_url_dns_ssrf_before_task_runs(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    with TestClient(app) as client:
        saved = client.put("/settings/providers/deepseek", json={
            "expected_revision": 0,
            "enabled": True,
            "api_key": "sk-test",
            "base_url": "https://llm.internal.example",
            "model": "deepseek-chat",
            "allow_custom_base_url": True,
        })
    assert saved.status_code == 200

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.8", 443))],
    )

    try:
        run_analysis(
            "examples/small_pytorch_project.zip",
            tmp_path / "outputs",
            text_llm_enabled=True,
            external_text_consent=True,
        )
    except ValueError as exc:
        assert "Private" in str(exc) or "blocked" in str(exc)
    else:
        raise AssertionError("custom provider DNS must be checked before the analysis graph runs")
