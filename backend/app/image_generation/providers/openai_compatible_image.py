from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from backend.app.image_generation.config import ImageProviderSettings
from backend.app.image_generation.exceptions import ImageGenerationError
from backend.app.image_generation.providers.base_provider import BaseImageProvider
from backend.app.image_generation.types import ImageGenerationRequest, ImageGenerationResponse, ImageProviderCapabilities


class OpenAICompatibleImageProvider(BaseImageProvider):
    def __init__(self, settings: ImageProviderSettings, *, timeout_seconds: float = 60) -> None:
        self.name = settings.name
        self.model = settings.model
        self.api_key = settings.api_key
        self.base_url = settings.base_url.rstrip("/")
        self.allowed_domains = settings.allowed_domains
        self.timeout_seconds = timeout_seconds
        self.capabilities = ImageProviderCapabilities(supports_json_prompt=True)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        if not self.configured:
            raise ImageGenerationError("image_provider_unconfigured", f"{self.name} is not configured.")
        payload = self._payload(request)
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self._endpoint(),
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ImageGenerationError("image_provider_timeout", f"{self.name} request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ImageGenerationError("image_provider_http_error", f"{self.name} request failed.") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            raise ImageGenerationError("image_provider_rate_limited", f"{self.name} rate limited the request.")
        if response.status_code >= 500:
            raise ImageGenerationError("image_provider_http_error", f"{self.name} returned a server error.")
        if response.status_code >= 400:
            raise ImageGenerationError("image_provider_rejected", f"{self.name} rejected the request.", recoverable=False)
        try:
            body = response.json()
        except ValueError as exc:
            raise ImageGenerationError("image_provider_invalid_json", f"{self.name} returned invalid JSON.") from exc
        return self._parse_response(body, latency_ms)

    def _endpoint(self) -> str:
        return self.base_url if self.base_url.endswith("/images/generations") else f"{self.base_url}/images/generations"

    def _payload(self, request: ImageGenerationRequest) -> dict[str, Any]:
        prompt = (
            "Create a beginner-friendly visual style layer for a teaching diagram. "
            "Do not add, remove, rename, or reinterpret modules, arrows, tensor shapes, formulas, or labels. "
            "The local compositor will draw all authoritative text, shapes, formulas, arrows, and legend. "
            "Untrusted public spec JSON:\n"
            + json.dumps(request.public_spec, ensure_ascii=False, sort_keys=True)
        )
        if len(prompt) > self.capabilities.max_prompt_chars:
            prompt = prompt[: self.capabilities.max_prompt_chars] + "...[TRUNCATED]"
        return {
            "model": self.model,
            "prompt": prompt,
            "size": f"{request.width}x{request.height}",
            "n": 1,
            "response_format": "b64_json",
        }

    def _parse_response(self, body: dict[str, Any], latency_ms: int) -> ImageGenerationResponse:
        data = body.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and first.get("b64_json"):
                return ImageGenerationResponse(
                    image_bytes=base64.b64decode(first["b64_json"]),
                    mime_type="image/png",
                    latency_ms=latency_ms,
                    metadata={"response_shape": "data.b64_json"},
                )
            if isinstance(first, dict) and first.get("url"):
                return ImageGenerationResponse(
                    remote_url=str(first["url"]),
                    mime_type="image/png",
                    latency_ms=latency_ms,
                    metadata={"response_shape": "data.url"},
                )
        if body.get("url"):
            return ImageGenerationResponse(
                remote_url=str(body["url"]),
                mime_type="image/png",
                latency_ms=latency_ms,
                metadata={"response_shape": "url"},
            )
        raise ImageGenerationError("image_provider_unsupported_response", f"{self.name} response did not contain an image.")
