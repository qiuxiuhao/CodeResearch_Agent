from __future__ import annotations

from typing import Any

import httpx

from backend.app.image_generation.config import ImageProviderSettings
from backend.app.image_generation.providers.openai_compatible_image import OpenAICompatibleImageProvider
from backend.app.image_generation.types import ImageGenerationRequest


class SeedreamProvider(OpenAICompatibleImageProvider):
    """Seedream request mapping is intentionally isolated from Qwen."""

    def __init__(self, settings: ImageProviderSettings, timeout_seconds: float = 60, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(settings, timeout_seconds=timeout_seconds, transport=transport)

    def _payload(self, request: ImageGenerationRequest) -> dict[str, Any]:
        payload = super()._payload(request)
        payload.pop("response_format", None)
        return payload
