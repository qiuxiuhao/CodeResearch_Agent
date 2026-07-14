from __future__ import annotations

from collections.abc import Callable

from backend.app.vision.exceptions import VisionProviderError
from backend.app.vision.providers.base_provider import BaseVisionProvider
from backend.app.vision.types import VisionProviderCapabilities, VisionRequest, VisionResponse


class MockVisionProvider(BaseVisionProvider):
    def __init__(
        self,
        name: str = "mock_vision",
        model: str = "mock-vision-model",
        response: dict | Callable[[VisionRequest], dict] | None = None,
        error: VisionProviderError | Callable[[VisionRequest], VisionProviderError | None] | None = None,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.model = model
        self.response = response or {}
        self.error = error
        self._configured = configured
        self.capabilities = VisionProviderCapabilities()
        self.calls: list[VisionRequest] = []

    @property
    def configured(self) -> bool:
        return self._configured

    def analyze_figure(self, request: VisionRequest) -> VisionResponse:
        self.calls.append(request)
        error = self.error(request) if callable(self.error) else self.error
        if error:
            raise error
        data = self.response(request) if callable(self.response) else self.response
        return VisionResponse(data=data, latency_ms=1, input_tokens=12, output_tokens=24, total_tokens=36)
