from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.llm.types import ProviderCapabilities, ProviderRequest, ProviderResponse


class BaseLLMProvider(ABC):
    name: str
    model: str
    capabilities: ProviderCapabilities

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def generate(self, request: ProviderRequest) -> ProviderResponse: ...
