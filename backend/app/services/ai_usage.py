from __future__ import annotations

from typing import Any

from backend.app.schemas.state import AgentState


def build_ai_usage(state: AgentState) -> dict[str, dict[str, Any]]:
    providers = state.get("ai_provider_config", {})
    manifest_warnings = state.get("teaching_diagram_manifest", {}).get("warnings", [])
    return _build_usage_groups({
        "text_analysis": (state.get("text_llm_enabled", False), state.get("external_text_consent", False), providers.get("text_analysis", {}), state.get("llm_budget", {}), state.get("llm_warnings", [])),
        "teaching_narrative": (state.get("teaching_narrative_llm_enabled", False), state.get("external_text_consent", False), providers.get("teaching_narrative", {}), state.get("teaching_plan_budget", {}), state.get("teaching_diagram_warnings", [])),
        "paper_vision": (state.get("vision_vlm_enabled", False), state.get("external_vision_consent", False), providers.get("paper_vision", {}), state.get("vision_budget", {}), state.get("paper_figure_analysis", {}).get("warnings", [])),
        "image_generation": (state.get("image_generation_enabled", False), state.get("external_image_consent", False), providers.get("image_generation", {}), state.get("teaching_image_budget", {}), manifest_warnings),
        "teaching_review": (state.get("teaching_review_vlm_enabled", False), state.get("external_teaching_review_consent", False), providers.get("teaching_review", {}), state.get("teaching_review_budget", {}), manifest_warnings),
    })


def build_ai_usage_from_outputs(llm: dict, figures: dict, teaching: dict) -> dict[str, dict[str, Any]]:
    budget = teaching.get("budget", {}) or {}
    warnings = teaching.get("warnings", [])
    return _build_usage_groups({
        "text_analysis": (llm.get("text_llm_enabled", False), llm.get("external_text_consent", False), {}, llm.get("budget", {}), llm.get("warnings", [])),
        "teaching_narrative": (teaching.get("teaching_narrative_llm_enabled", False), llm.get("external_text_consent", False), {}, budget.get("teaching_plan", {}), warnings),
        "paper_vision": (figures.get("vision_vlm_enabled", False), figures.get("external_vision_consent", False), {}, figures.get("budget", {}), figures.get("warnings", [])),
        "image_generation": (teaching.get("image_generation_enabled", False), teaching.get("external_image_consent", False), {}, budget.get("teaching_image", {}), warnings),
        "teaching_review": (teaching.get("teaching_review_vlm_enabled", False), teaching.get("external_teaching_review_consent", False), {}, budget.get("teaching_review", {}), warnings),
    })


_FAILURE_PREFIXES = {
    "text_analysis": ("llm_",),
    "teaching_narrative": ("teaching_", "llm_"),
    "paper_vision": ("vlm_",),
    "image_generation": ("image_",),
    "teaching_review": ("vlm_", "review_"),
}


def _build_usage_groups(groups: dict[str, tuple[object, object, dict, dict, list]]) -> dict[str, dict[str, Any]]:
    return {
        name: _usage_group(
            enabled=bool(values[0]), consent=bool(values[1]), provider_info=values[2],
            budget=values[3], warnings=values[4], failure_prefixes=_FAILURE_PREFIXES[name],
        )
        for name, values in groups.items()
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
