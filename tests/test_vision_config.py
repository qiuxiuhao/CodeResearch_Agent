from backend.app.llm.config import LLMSettings
from backend.app.vision.config import VisionSettings


def test_text_and_vision_environment_switches_are_independent(monkeypatch):
    monkeypatch.setenv("TEXT_LLM_ENABLED", "true")
    monkeypatch.setenv("VISION_VLM_ENABLED", "false")
    assert LLMSettings.from_env().text_llm_enabled is True
    assert VisionSettings.from_env().enabled is False

    assert LLMSettings.from_env(text_llm_enabled=False).text_llm_enabled is False
    assert VisionSettings.from_env(True).enabled is True


def test_vision_public_config_exposes_no_secrets_and_capabilities_default_conservative(monkeypatch):
    monkeypatch.setenv("QWEN_VL_API_KEY", "vision-secret")
    settings = VisionSettings.from_env()
    payload = settings.public_config()
    assert payload["providers"]["qwen_vl"]["configured"] is True
    assert "vision-secret" not in str(payload)
    assert settings.qwen_vl.supports_json_object is False
    assert settings.glm_v.supports_json_object is False
