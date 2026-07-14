from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.vision.types import VisionProviderCapabilities, VisionRequest, VisionResponse


class BaseVisionProvider(ABC):
    name: str
    model: str
    capabilities: VisionProviderCapabilities

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def analyze_figure(self, request: VisionRequest) -> VisionResponse: ...
