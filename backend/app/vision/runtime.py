from __future__ import annotations

from dataclasses import dataclass

from backend.app.llm.budget import BudgetManager
from backend.app.vision.cache import VisionCache
from backend.app.vision.config import VisionSettings
from backend.app.vision.providers.base_provider import BaseVisionProvider
from backend.app.vision.providers.glm_v_provider import GLMVProvider
from backend.app.vision.providers.qwen_vl_provider import QwenVLProvider
from backend.app.vision.router import VisionModelRouter


@dataclass(slots=True)
class VisionRuntime:
    settings: VisionSettings
    budget: BudgetManager
    router: VisionModelRouter


def create_vision_runtime(settings: VisionSettings, providers: list[BaseVisionProvider] | None = None) -> VisionRuntime:
    budget = BudgetManager(settings.max_figure_analyses, settings.max_provider_requests)
    configured_providers = providers or [
        QwenVLProvider(settings.qwen_vl, settings.timeout_seconds),
        GLMVProvider(settings.glm_v, settings.timeout_seconds),
    ]
    cache = VisionCache(settings.cache_path, settings.cache_enabled)
    return VisionRuntime(settings, budget, VisionModelRouter(settings, configured_providers, budget, cache))
