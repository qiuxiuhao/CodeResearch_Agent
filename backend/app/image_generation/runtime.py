from __future__ import annotations

from dataclasses import dataclass

from backend.app.image_generation.cache import ImageGenerationCache
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.providers.base_provider import BaseImageProvider
from backend.app.image_generation.providers.qwen_image_provider import QwenImageProvider
from backend.app.image_generation.providers.seedream_provider import SeedreamProvider
from backend.app.image_generation.router import ImageGenerationRouter
from backend.app.llm.budget import BudgetManager


@dataclass(slots=True)
class ImageGenerationRuntime:
    settings: ImageGenerationSettings
    budget: BudgetManager
    router: ImageGenerationRouter


def create_image_generation_runtime(
    settings: ImageGenerationSettings,
    providers: list[BaseImageProvider] | None = None,
) -> ImageGenerationRuntime:
    budget = BudgetManager(4, settings.max_provider_requests)
    configured_providers = providers or [
        QwenImageProvider(settings.qwen_image, settings.qwen_image.timeout_seconds),
        SeedreamProvider(settings.seedream, settings.seedream.timeout_seconds),
    ]
    cache = ImageGenerationCache(settings.cache_path, settings.cache_asset_root, enabled=settings.cache_enabled)
    return ImageGenerationRuntime(settings, budget, ImageGenerationRouter(settings, configured_providers, budget, cache))
