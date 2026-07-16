from __future__ import annotations

from typing import Any

from backend.app.schemas.state import AgentState


def build_ai_usage(state: AgentState) -> dict[str, dict[str, Any]]:
    providers = state.get("ai_provider_config", {})
    return {
        "text_analysis": _usage_group(
            enabled=state.get("text_llm_enabled", False),
            consent=state.get("external_text_consent", False),
            provider_info=providers.get("text_analysis", {}),
            budget=state.get("llm_budget", {}),
            warnings=state.get("llm_warnings", []),
            failure_prefixes=("llm_",),
        ),
        "teaching_narrative": _usage_group(
            enabled=state.get("teaching_narrative_llm_enabled", False),
            consent=state.get("external_text_consent", False),
            provider_info=providers.get("teaching_narrative", {}),
            budget=state.get("teaching_plan_budget", {}),
            warnings=state.get("teaching_diagram_warnings", []),
            failure_prefixes=("teaching_", "llm_"),
        ),
        "paper_vision": _usage_group(
            enabled=state.get("vision_vlm_enabled", False),
            consent=state.get("external_vision_consent", False),
            provider_info=providers.get("paper_vision", {}),
            budget=state.get("vision_budget", {}),
            warnings=state.get("paper_figure_analysis", {}).get("warnings", []),
            failure_prefixes=("vlm_",),
        ),
        "image_generation": _usage_group(
            enabled=state.get("image_generation_enabled", False),
            consent=state.get("external_image_consent", False),
            provider_info=providers.get("image_generation", {}),
            budget=state.get("teaching_image_budget", {}),
            warnings=state.get("teaching_diagram_manifest", {}).get("warnings", []),
            failure_prefixes=("image_",),
        ),
        "teaching_review": _usage_group(
            enabled=state.get("teaching_review_vlm_enabled", False),
            consent=state.get("external_teaching_review_consent", False),
            provider_info=providers.get("teaching_review", {}),
            budget=state.get("teaching_review_budget", {}),
            warnings=state.get("teaching_diagram_manifest", {}).get("warnings", []),
            failure_prefixes=("vlm_", "review_"),
        ),
    }


def build_ai_usage_from_outputs(llm: dict, figures: dict, teaching: dict) -> dict[str, dict[str, Any]]:
    budget = teaching.get("budget", {}) or {}
    return {
        "text_analysis": _usage_group(
            enabled=llm.get("text_llm_enabled", False),
            consent=llm.get("external_text_consent", False),
            provider_info={},
            budget=llm.get("budget", {}),
            warnings=llm.get("warnings", []),
            failure_prefixes=("llm_",),
        ),
        "teaching_narrative": _usage_group(
            enabled=teaching.get("teaching_narrative_llm_enabled", False),
            consent=llm.get("external_text_consent", False),
            provider_info={},
            budget=budget.get("teaching_plan", {}),
            warnings=teaching.get("warnings", []),
            failure_prefixes=("teaching_", "llm_"),
        ),
        "paper_vision": _usage_group(
            enabled=figures.get("vision_vlm_enabled", False),
            consent=figures.get("external_vision_consent", False),
            provider_info={},
            budget=figures.get("budget", {}),
            warnings=figures.get("warnings", []),
            failure_prefixes=("vlm_",),
        ),
        "image_generation": _usage_group(
            enabled=teaching.get("image_generation_enabled", False),
            consent=teaching.get("external_image_consent", False),
            provider_info={},
            budget=budget.get("teaching_image", {}),
            warnings=teaching.get("warnings", []),
            failure_prefixes=("image_",),
        ),
        "teaching_review": _usage_group(
            enabled=teaching.get("teaching_review_vlm_enabled", False),
            consent=teaching.get("external_teaching_review_consent", False),
            provider_info={},
            budget=budget.get("teaching_review", {}),
            warnings=teaching.get("warnings", []),
            failure_prefixes=("vlm_", "review_"),
        ),
    }


def _usage_group(
    *,
    enabled: bool,
    consent: bool,
    provider_info: dict,
    budget: dict,
    warnings: list,
    failure_prefixes: tuple[str, ...],
) -> dict[str, Any]:
    normalized_warnings = [_warning_code(item) for item in warnings]
    group = {
        "enabled": bool(enabled),
        "consent": bool(consent),
        "provider": provider_info.get("provider"),
        "model": provider_info.get("model"),
        "request_count": budget.get("sent_provider_requests", 0),
        "budget_limit": budget.get("max_provider_requests", 0),
        "selected_entities": budget.get("selected_entities", 0),
        "cache_hits": budget.get("cache_hits", 0),
        "fallbacks": budget.get("fallbacks", 0),
        "failures": sum(
            1 for code in normalized_warnings
            if code and code.startswith(failure_prefixes) and ("failed" in code or "error" in code or "timeout" in code)
        ),
        "warnings": [code for code in normalized_warnings if code],
    }
    if "configured" in provider_info:
        group["configured"] = bool(provider_info.get("configured"))
    return group


def _warning_code(item: Any) -> str | None:
    if isinstance(item, dict):
        return str(item.get("code") or "") or None
    if isinstance(item, str):
        return item
    return None
