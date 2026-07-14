from __future__ import annotations

from typing import Any

from backend.app.vision.providers.http_provider import HTTPVisionProvider
from backend.app.vision.types import VisionRequest


class GLMVProvider(HTTPVisionProvider):
    """GLM request mapping is intentionally isolated from Qwen/OpenAI adapters."""

    def _build_payload(self, request: VisionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._schema_prompt(request)},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": self._data_url(request)}},
                        {"type": "text", "text": self._user_text(request)},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": request.max_output_tokens,
        }
        if self.capabilities.supports_json_object:
            payload["response_format"] = {"type": "json_object"}
        return payload
