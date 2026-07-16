from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from backend.app.vision.config import VisionProviderSettings
from backend.app.vision.exceptions import VisionProviderError
from backend.app.vision.providers.base_provider import BaseVisionProvider
from backend.app.vision.types import VisionProviderCapabilities, VisionRequest, VisionResponse
from backend.app.utils.provider_response import optional_usage_int, parse_json_object


class HTTPVisionProvider(BaseVisionProvider):
    """Shared transport only; each supplier owns its request mapping."""

    def __init__(
        self,
        settings: VisionProviderSettings,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = settings.name
        self.api_key = settings.api_key
        self.base_url = settings.base_url.rstrip("/")
        self.model = settings.model
        self.disable_thinking = settings.disable_thinking
        self.timeout_seconds = timeout_seconds
        self.max_retries = settings.max_retries
        self.max_output_tokens = settings.max_output_tokens
        self._client = client
        self.capabilities = VisionProviderCapabilities(
            supports_json_schema=False,
            supports_json_object=settings.supports_json_object,
            supports_tool_calling=False,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def analyze_figure(self, request: VisionRequest) -> VisionResponse:
        if not self.configured:
            raise VisionProviderError("vlm_provider_unconfigured", f"Provider {self.name} is not configured.")
        payload = self._build_payload(request)
        started = time.monotonic()
        try:
            if self._client is not None:
                response = self._client.post(self._endpoint(), headers=self._headers(), json=payload)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(self._endpoint(), headers=self._headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise VisionProviderError("vlm_timeout", f"{self.name} request timed out.") from exc
        except httpx.HTTPError as exc:
            raise VisionProviderError("vlm_http_error", f"{self.name} request failed: {type(exc).__name__}.") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            raise VisionProviderError("vlm_rate_limited", f"{self.name} rate limited the request.")
        if response.status_code >= 500:
            raise VisionProviderError("vlm_http_error", f"{self.name} returned HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise VisionProviderError(
                "vlm_http_error", f"{self.name} rejected the request with HTTP {response.status_code}.", recoverable=False
            )
        try:
            body = response.json()
            content = self._response_content(body)
            data = parse_json_object(content, allow_embedded=True)
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise VisionProviderError("vlm_invalid_json", f"{self.name} returned invalid structured content.") from exc
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        return VisionResponse(
            data=data,
            latency_ms=latency_ms,
            input_tokens=optional_usage_int(usage.get("prompt_tokens")),
            output_tokens=optional_usage_int(usage.get("completion_tokens")),
            total_tokens=optional_usage_int(usage.get("total_tokens")),
        )

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _schema_prompt(self, request: VisionRequest) -> str:
        return (
            request.system_prompt
            + "\n<OUTPUT_SCHEMA>\n"
            + json.dumps(request.response_model.model_json_schema(), ensure_ascii=False)
            + "\n</OUTPUT_SCHEMA>\n只返回一个符合 Schema 的 JSON object，不要输出 Markdown。"
        )

    def _data_url(self, request: VisionRequest) -> str:
        encoded = base64.b64encode(request.image_bytes).decode("ascii")
        return f"data:{request.mime_type};base64,{encoded}"

    def _user_text(self, request: VisionRequest) -> str:
        return (
            "<UNTRUSTED_CAPTION_AND_PAPER_CONTEXT>\n"
            + json.dumps(request.input_payload, ensure_ascii=False, sort_keys=True)
            + "\n</UNTRUSTED_CAPTION_AND_PAPER_CONTEXT>"
        )

    def _build_payload(self, request: VisionRequest) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _response_content(body: dict[str, Any]) -> Any:
        return body["choices"][0]["message"]["content"]
