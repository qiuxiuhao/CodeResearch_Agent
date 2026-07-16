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


class QwenImageProvider(BaseImageProvider):
    """DashScope Qwen-Image mapping.

    This provider intentionally does not share the OpenAI-compatible
    /images/generations mapping used by other vendors.
    """

    def __init__(
        self,
        settings: ImageProviderSettings,
        timeout_seconds: float = 60,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = settings.name
        self.model = settings.model
        self.api_key = settings.api_key
        self.base_url = settings.base_url.rstrip("/")
        self.endpoint_path = settings.endpoint_path or "/api/v1/services/aigc/multimodal-generation/generation"
        self.workspace = settings.workspace
        self.allowed_domains = settings.allowed_domains
        self.supports_async = settings.supports_async
        self.request_width = settings.request_width
        self.request_height = settings.request_height
        self._settings = settings
        self.timeout_seconds = timeout_seconds
        self.max_retries = settings.max_retries
        self._transport = transport
        self.capabilities = ImageProviderCapabilities(
            supports_json_prompt=True,
            supports_negative_prompt=True,
            supported_mime_types=["image/png", "image/jpeg", "image/webp"],
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.model.strip() and self.base_url.strip())

    def request_size(self) -> tuple[int, int]:
        return self._settings.validate_request_size()

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        if not self.configured:
            raise ImageGenerationError("image_provider_unconfigured", f"{self.name} is not configured.")
        if self.supports_async:
            raise ImageGenerationError(
                "image_provider_async_not_supported",
                "v1.3.4 only supports synchronous teaching-image generation.",
                recoverable=False,
            )
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(self._endpoint(), headers=self._headers(), json=self._payload(request))
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
        if self.base_url.endswith(self.endpoint_path):
            return self.base_url
        return f"{self.base_url}/{self.endpoint_path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "disable",
        }
        if self.workspace:
            headers["X-DashScope-WorkSpace"] = self.workspace
        return headers

    def _payload(self, request: ImageGenerationRequest) -> dict[str, Any]:
        prompt = (
            "Create only a visual background/style layer for a beginner teaching diagram. "
            "Do not render authoritative labels, arrows, tensor shapes, formulas, or legends; "
            "the local compositor will draw those deterministic elements. Public spec JSON:\n"
            + json.dumps(request.public_spec, ensure_ascii=False, sort_keys=True)
        )
        if len(prompt) > self.capabilities.max_prompt_chars:
            prompt = prompt[: self.capabilities.max_prompt_chars] + "...[TRUNCATED]"
        return {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"text": prompt},
                        ],
                    }
                ]
            },
            "parameters": {
                "size": f"{request.width}*{request.height}",
                "n": 1,
                "watermark": False,
            },
        }

    def _parse_response(self, body: dict[str, Any], latency_ms: int) -> ImageGenerationResponse:
        task_status = str(body.get("output", {}).get("task_status") or "").upper()
        if task_status and task_status not in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
            raise ImageGenerationError("image_provider_async_unfinished", "Qwen-Image returned an unfinished async task.")
        content = _first_message_content(body)
        for item in content:
            if not isinstance(item, dict):
                continue
            image = item.get("image")
            if isinstance(image, str) and image.startswith(("http://", "https://")):
                return ImageGenerationResponse(
                    remote_url=image,
                    mime_type="image/png",
                    latency_ms=latency_ms,
                    metadata={"response_shape": "output.choices.message.content.image"},
                )
            if isinstance(image, str) and image:
                try:
                    return ImageGenerationResponse(
                        image_bytes=base64.b64decode(image),
                        mime_type="image/png",
                        latency_ms=latency_ms,
                        metadata={"response_shape": "output.choices.message.content.image_b64"},
                    )
                except Exception as exc:
                    raise ImageGenerationError("image_provider_unsupported_response", "Qwen-Image image field was not URL or base64.") from exc
        raise ImageGenerationError("image_provider_unsupported_response", "Qwen-Image response did not contain an image.")


def _first_message_content(body: dict[str, Any]) -> list[Any]:
    choices = body.get("output", {}).get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []
