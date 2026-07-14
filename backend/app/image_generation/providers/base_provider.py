from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.image_generation.types import (
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageProviderCapabilities,
)


class BaseImageProvider(ABC):
    name: str
    model: str
    capabilities: ImageProviderCapabilities

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse: ...
