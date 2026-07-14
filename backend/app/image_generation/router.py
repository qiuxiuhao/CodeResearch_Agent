from __future__ import annotations

from pathlib import Path
from typing import Iterable

from backend.app.image_generation.cache import ImageGenerationCache
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.downloader import SafeImageDownloader
from backend.app.image_generation.exceptions import ImageGenerationError
from backend.app.image_generation.providers.base_provider import BaseImageProvider
from backend.app.image_generation.safety import write_validated_image
from backend.app.image_generation.types import ImageGenerationRequest, ImageRouterResult
from backend.app.llm.budget import BudgetManager


class ImageGenerationRouter:
    def __init__(
        self,
        settings: ImageGenerationSettings,
        providers: Iterable[BaseImageProvider],
        budget: BudgetManager,
        cache: ImageGenerationCache,
    ) -> None:
        self.settings = settings
        self.providers = list(providers)
        self.budget = budget
        self.cache = cache

    @property
    def has_available_provider(self) -> bool:
        return any(provider.configured for provider in self.providers)

    def generate(self, request: ImageGenerationRequest) -> ImageRouterResult:
        warnings: list[dict] = []
        for provider_index, provider in enumerate([item for item in self.providers if item.configured]):
            cache_key = {
                "provider": provider.name,
                "model": provider.model,
                "prompt_version": request.prompt_version,
                "schema_version": request.schema_version,
                "public_spec_hash": request.public_spec.get("public_spec_hash"),
                "diagram_spec_hash": request.public_spec.get("public_spec_hash"),
                "width": request.width,
                "height": request.height,
            }
            try:
                cached = self.cache.get(cache_key)
            except Exception:
                cached = None
                warnings.append(_warning("image_cache_error", request.diagram_id, provider=provider.name))
            if cached and cached.get("cached_asset_path"):
                path = Path(cached["cached_asset_path"])
                if path.is_file():
                    self.budget.record_cache_hit()
                    return ImageRouterResult(path, cached.get("mime_type", "image/png"), {**cached, "cache_hit": True}, warnings)

            reservation = self.budget.try_reserve_provider_request(
                provider.name, "teaching_image_generate", request.diagram_id,
                fallback=provider_index > 0,
            )
            if not reservation.allowed:
                warnings.append(_warning("image_provider_request_budget_exceeded", request.diagram_id, provider=provider.name))
                return ImageRouterResult(None, None, {}, warnings)
            try:
                response = provider.generate_image(request)
                image_bytes = response.image_bytes
                mime_type = response.mime_type
                if response.remote_url:
                    downloader = SafeImageDownloader(
                        getattr(provider, "allowed_domains", []),
                        timeout_seconds=self.settings.timeout_seconds,
                        max_bytes=request.max_output_bytes,
                    )
                    image_bytes, mime_type = downloader.download(response.remote_url)
                if not image_bytes:
                    raise ImageGenerationError("image_provider_empty_response", "Image provider did not return image bytes.")
                output_path = request.output_dir / "generated_raw.png"
                info = write_validated_image(
                    output_path,
                    image_bytes,
                    mime_type=mime_type,
                    max_bytes=request.max_output_bytes,
                    max_width=self.settings.max_width,
                    max_height=self.settings.max_height,
                )
                self.budget.record_request_result(reservation.reservation_id, "success")
                metadata = {
                    **info,
                    "provider": provider.name,
                    "model": provider.model,
                    "latency_ms": response.latency_ms,
                    "cache_hit": False,
                }
                try:
                    self.cache.set(cache_key, image_bytes, metadata)
                except Exception:
                    warnings.append(_warning("image_cache_error", request.diagram_id, provider=provider.name))
                return ImageRouterResult(output_path, info["mime_type"], metadata, warnings)
            except ImageGenerationError as exc:
                self.budget.record_request_result(reservation.reservation_id, "failed")
                warnings.append(_warning(exc.code, request.diagram_id, provider=provider.name))
                if not exc.recoverable:
                    break
            except Exception:
                self.budget.record_request_result(reservation.reservation_id, "failed")
                warnings.append(_warning("image_provider_unknown_error", request.diagram_id, provider=provider.name))
        if not self.providers or not any(provider.configured for provider in self.providers):
            warnings.append(_warning("image_provider_unconfigured", request.diagram_id))
        return ImageRouterResult(None, None, {}, warnings)


def _warning(code: str, diagram_id: str, *, provider: str | None = None) -> dict:
    return {
        "code": code,
        "task_type": "teaching_image_generate",
        "context_id": diagram_id,
        "provider": provider,
        "message": code.replace("_", " "),
        "recoverable": True,
    }
