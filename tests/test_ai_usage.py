from backend.app.services.ai_usage import build_ai_usage, build_ai_usage_from_outputs


def test_live_and_historical_usage_normalize_the_same_five_groups():
    state = {
        "text_llm_enabled": True,
        "external_text_consent": True,
        "llm_budget": {"sent_provider_requests": 2, "max_provider_requests": 5},
        "llm_warnings": [{"code": "llm_timeout"}],
        "ai_provider_config": {"text_analysis": {"provider": "qwen", "model": "qwen-plus", "configured": True}},
    }
    historical = build_ai_usage_from_outputs(
        {"text_llm_enabled": True, "external_text_consent": True, "budget": state["llm_budget"], "warnings": state["llm_warnings"]},
        {},
        {},
    )
    live = build_ai_usage(state)  # type: ignore[arg-type]

    assert set(live) == set(historical) == {
        "text_analysis", "teaching_narrative", "paper_vision", "image_generation", "teaching_review"
    }
    assert live["text_analysis"]["request_count"] == historical["text_analysis"]["request_count"] == 2
    assert live["text_analysis"]["failures"] == historical["text_analysis"]["failures"] == 1
    assert live["text_analysis"]["provider"] == "qwen"
    assert historical["text_analysis"]["provider"] is None
