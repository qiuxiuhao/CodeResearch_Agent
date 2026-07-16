from __future__ import annotations

import httpx

from backend.app.llm.config import ProviderSettings
from backend.app.llm.providers.openai_compatible import OpenAICompatibleProvider
from backend.app.llm.types import ProviderCapabilities


class QwenProvider(OpenAICompatibleProvider):
    def __init__(self, settings: ProviderSettings, timeout_seconds: float, client: httpx.Client | None = None) -> None:
        super().__init__(
            name="qwen",
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            capabilities=ProviderCapabilities(supports_json_object=True),
            timeout_seconds=timeout_seconds,
            max_retries=settings.max_retries,
            max_output_tokens=settings.max_output_tokens,
            client=client,
        )
