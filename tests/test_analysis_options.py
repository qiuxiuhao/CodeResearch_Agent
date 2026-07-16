import json

import pytest

from backend.app.services.analysis_options import (
    AnalysisOptionsError,
    ProviderRuntimeContext,
    create_provider_runtime_context,
    resolve_analysis_options,
)


def test_resolved_analysis_options_are_json_safe_and_secret_free(monkeypatch, tmp_path):
    secret = "sk-options-must-not-leak"
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    options, settings = resolve_analysis_options(text_llm_enabled=False)
    payload = options.state_dump()
    encoded = json.dumps(payload)

    assert json.loads(encoded) == payload
    assert secret not in encoded
    assert all("key" not in name.lower() and "secret" not in name.lower() for name in payload)
    assert secret == settings.llm.deepseek.api_key


def test_provider_runtime_context_has_no_public_serialization_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    _, settings = resolve_analysis_options(text_llm_enabled=False)
    context = create_provider_runtime_context(settings)

    assert isinstance(context, ProviderRuntimeContext)
    assert not hasattr(context, "model_dump")
    assert not hasattr(context, "state_dump")


def test_shared_options_resolver_enforces_consent_boundaries(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", str(tmp_path / "secrets.json"))
    with pytest.raises(AnalysisOptionsError, match="external_text_consent"):
        resolve_analysis_options(text_llm_enabled=True, external_text_consent=False)
    with pytest.raises(AnalysisOptionsError, match="image_generation_enabled") as exc_info:
        resolve_analysis_options(
            image_generation_enabled=False,
            teaching_review_vlm_enabled=True,
            external_image_consent=True,
            external_teaching_review_consent=True,
        )
    assert exc_info.value.status_code == 422
