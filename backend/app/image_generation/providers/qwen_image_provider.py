from __future__ import annotations

from backend.app.image_generation.config import ImageProviderSettings
from backend.app.image_generation.providers.openai_compatible_image import OpenAICompatibleImageProvider


class QwenImageProvider(OpenAICompatibleImageProvider):
    """Qwen-Image request mapping is kept separate from Seedream."""

    def __init__(self, settings: ImageProviderSettings, timeout_seconds: float = 60) -> None:
        super().__init__(settings, timeout_seconds=timeout_seconds)
