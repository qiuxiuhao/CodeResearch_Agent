from __future__ import annotations

from collections.abc import Callable

from backend.app.llm.exceptions import ProviderError
from backend.app.llm.providers.base_provider import BaseLLMProvider
from backend.app.llm.types import ProviderCapabilities, ProviderRequest, ProviderResponse


class MockProvider(BaseLLMProvider):
    def __init__(
        self,
        name: str = "mock",
        model: str = "mock-model",
        responses: dict[str, dict | Callable[[ProviderRequest], dict]] | None = None,
        error: ProviderError | Callable[[ProviderRequest], ProviderError | None] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.responses = responses or {}
        self.error = error
        self.capabilities = ProviderCapabilities(supports_json_schema=True, supports_json_object=True)
        self.calls: list[ProviderRequest] = []

    @property
    def configured(self) -> bool:
        return True

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        error = self.error(request) if callable(self.error) else self.error
        if error:
            raise error
        response = self.responses.get(request.task_type, {})
        data = response(request) if callable(response) else response
        return ProviderResponse(data=data, latency_ms=1, input_tokens=10, output_tokens=20, total_tokens=30)
