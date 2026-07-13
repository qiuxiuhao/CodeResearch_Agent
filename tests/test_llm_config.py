from backend.app.llm.config import LLMSettings


def test_analysis_mode_precedence(monkeypatch):
    monkeypatch.setenv("ANALYSIS_MODE", "hybrid")
    assert LLMSettings.from_env().analysis_mode == "hybrid"
    assert LLMSettings.from_env("rule").analysis_mode == "rule"


def test_public_config_contains_no_api_keys(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value")
    payload = LLMSettings.from_env().public_config()
    assert payload["providers"]["deepseek"]["configured"] is True
    assert "secret-value" not in str(payload)
    assert payload["max_total_entities"] != payload["max_provider_requests"]
