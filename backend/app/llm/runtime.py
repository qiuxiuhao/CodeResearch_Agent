from __future__ import annotations

from dataclasses import dataclass

from backend.app.llm.budget import BudgetManager
from backend.app.llm.cache import LLMCache
from backend.app.llm.config import LLMSettings
from backend.app.llm.providers.base_provider import BaseLLMProvider
from backend.app.llm.providers.deepseek_provider import DeepSeekProvider
from backend.app.llm.providers.qwen_provider import QwenProvider
from backend.app.llm.router import ModelRouter


@dataclass(slots=True)
class LLMRuntime:
    settings: LLMSettings
    budget: BudgetManager
    router: ModelRouter


def create_llm_runtime(settings: LLMSettings, providers: list[BaseLLMProvider] | None = None) -> LLMRuntime:
    budget = BudgetManager(settings.max_total_entities, settings.max_provider_requests)
    configured_providers = providers or [
        DeepSeekProvider(settings.deepseek, settings.timeout_seconds),
        QwenProvider(settings.qwen, settings.timeout_seconds),
    ]
    cache = LLMCache(settings.cache_path, settings.cache_enabled)
    return LLMRuntime(settings, budget, ModelRouter(settings, configured_providers, budget, cache))
