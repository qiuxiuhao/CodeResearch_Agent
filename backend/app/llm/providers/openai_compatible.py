from __future__ import annotations

import json
import time
from typing import Any

import httpx

from backend.app.llm.exceptions import ProviderError
from backend.app.llm.types import ProviderCapabilities, ProviderRequest, ProviderResponse
from backend.app.llm.providers.base_provider import BaseLLMProvider
from backend.app.utils.provider_response import optional_usage_int, parse_json_object


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        capabilities: ProviderCapabilities,
        timeout_seconds: float,
        max_retries: int = 1,
        max_output_tokens: int = 1200,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.capabilities = capabilities
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.configured:
            raise ProviderError("llm_provider_unconfigured", f"Provider {self.name} is not configured.")
        data_tag = "UNTRUSTED_PAPER_DATA" if request.task_type == "paper_code_align" else "UNTRUSTED_CODE_DATA"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": request.system_prompt
                    + "\n<OUTPUT_SCHEMA>\n"
                    + json.dumps(request.response_model.model_json_schema(), ensure_ascii=False)
                    + "\n</OUTPUT_SCHEMA>",
                },
                {
                    "role": "user",
                    "content": f"<{data_tag}>\n"
                    + json.dumps(request.input_payload, ensure_ascii=False, sort_keys=True)
                    + f"\n</{data_tag}>",
                },
            ],
            "temperature": 0.1,
            "max_tokens": request.max_output_tokens,
        }
        if self.capabilities.supports_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.response_model.__name__, "schema": request.response_model.model_json_schema()},
            }
        elif self.capabilities.supports_json_object:
            payload["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        try:
            if self._client is not None:
                response = self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
        except httpx.TimeoutException as exc:
            raise ProviderError("llm_timeout", f"{self.name} request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("llm_http_error", f"{self.name} request failed: {type(exc).__name__}.") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            raise ProviderError("llm_rate_limited", f"{self.name} rate limited the request.")
        if response.status_code >= 500:
            raise ProviderError("llm_http_error", f"{self.name} returned HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise ProviderError("llm_http_error", f"{self.name} rejected the request with HTTP {response.status_code}.", recoverable=False)
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            data = parse_json_object(content)
        except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("llm_invalid_json", f"{self.name} returned invalid structured content.") from exc
        usage = body.get("usage", {})
        return ProviderResponse(
            data=data,
            latency_ms=latency_ms,
            input_tokens=optional_usage_int(usage.get("prompt_tokens")),
            output_tokens=optional_usage_int(usage.get("completion_tokens")),
            total_tokens=optional_usage_int(usage.get("total_tokens")),
        )
