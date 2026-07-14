from __future__ import annotations

from collections.abc import Callable

import fitz

from backend.app.image_generation.exceptions import ImageGenerationError
from backend.app.image_generation.providers.base_provider import BaseImageProvider
from backend.app.image_generation.types import ImageGenerationRequest, ImageGenerationResponse, ImageProviderCapabilities


class MockImageProvider(BaseImageProvider):
    def __init__(
        self,
        name: str = "mock_image",
        model: str = "mock-image-model",
        image_bytes: bytes | Callable[[ImageGenerationRequest], bytes] | None = None,
        error: ImageGenerationError | Callable[[ImageGenerationRequest], ImageGenerationError | None] | None = None,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.model = model
        self._image_bytes = image_bytes
        self._error = error
        self._configured = configured
        self.capabilities = ImageProviderCapabilities()
        self.calls: list[ImageGenerationRequest] = []

    @property
    def configured(self) -> bool:
        return self._configured

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        self.calls.append(request)
        error = self._error(request) if callable(self._error) else self._error
        if error:
            raise error
        data = self._image_bytes(request) if callable(self._image_bytes) else self._image_bytes
        return ImageGenerationResponse(image_bytes=data or _synthetic_png(request.width, request.height), latency_ms=1)


def _synthetic_png(width: int, height: int) -> bytes:
    document = fitz.open()
    page = document.new_page(width=min(width, 512), height=min(height, 320))
    page.draw_rect(fitz.Rect(0, 0, page.rect.width, page.rect.height), fill=(0.93, 0.95, 0.98), color=None)
    page.draw_rect(fitz.Rect(40, 70, page.rect.width - 40, page.rect.height - 70), color=(0.20, 0.25, 0.33), width=2)
    page.insert_text((64, 130), "Mock visual layer", fontsize=18, color=(0.10, 0.12, 0.18))
    data = page.get_pixmap(alpha=False).tobytes("png")
    document.close()
    return data
