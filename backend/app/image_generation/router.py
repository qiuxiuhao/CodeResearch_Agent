from __future__ import annotations

from pathlib import Path
from shutil import copyfile
from dataclasses import replace
from typing import Iterable

from backend.app.image_generation.cache import ImageGenerationCache
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.downloader import SafeImageDownloader
from backend.app.image_generation.exceptions import ImageGenerationError
from backend.app.image_generation.providers.base_provider import BaseImageProvider
from backend.app.image_generation.safety import validate_image_file, write_validated_image
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

    def generate(self, request: ImageGenerationRequest, *, provider_names: list[str] | None = None) -> ImageRouterResult:
        warnings: list[dict] = []
        providers = [item for item in self.providers if item.configured]
        if provider_names is not None:
            wanted = set(provider_names)
            providers = [item for item in providers if item.name in wanted]
        for provider_index, provider in enumerate(providers):
            try:
                provider_width, provider_height = getattr(provider, "request_size")()
            except AttributeError:
                provider_width, provider_height = request.width, request.height
            except Exception:
                warnings.append(_warning("image_provider_invalid_request_size", request.diagram_id, provider=provider.name))
                continue
            provider_request = replace(request, width=provider_width, height=provider_height)
            cache_key = {
                "provider": provider.name,
                "model": provider.model,
                "prompt_version": request.prompt_version,
                "schema_version": request.schema_version,
                "public_spec_hash": request.public_spec.get("public_spec_hash"),
                "diagram_spec_hash": request.public_spec.get("public_spec_hash"),
                "width": provider_width,
                "height": provider_height,
            }
            try:
                cached = self.cache.get(cache_key)
            except Exception:
                cached = None
                warnings.append(_warning("image_cache_error", request.diagram_id, provider=provider.name))
            if cached and cached.get("cached_asset_path"):
                try:
                    path = Path(cached["cached_asset_path"])
                    info = _validate_cached(path, cached, provider_request, self.settings)
                    output_path = request.output_dir / "generated_raw.png"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    _copy_or_link(path, output_path)
                    info = {**cached, **info, "cache_hit": True, "current_task_asset": str(output_path)}
                    self.budget.record_cache_hit()
                    return ImageRouterResult(output_path, "image/png", info, warnings)
                except Exception:
                    warnings.append(_warning("image_cache_error", request.diagram_id, provider=provider.name))

            max_retries = int(getattr(provider, "max_retries", self.settings.max_retries))
            for attempt in range(max_retries + 1):
                reservation = self.budget.try_reserve_provider_request(
                    provider.name, "teaching_image_generate", request.diagram_id,
                    retry=attempt > 0,
                    fallback=provider_index > 0 and attempt == 0,
                )
                if not reservation.allowed:
                    warnings.append(_warning("image_provider_request_budget_exceeded", request.diagram_id, provider=provider.name))
                    return ImageRouterResult(None, None, {}, warnings)
                try:
                    response = provider.generate_image(provider_request)
                    image_bytes = response.image_bytes
                    mime_type = response.mime_type
                    if response.remote_url:
                        downloader = SafeImageDownloader(
                            getattr(provider, "allowed_domains", []),
                            timeout_seconds=float(getattr(provider, "timeout_seconds", self.settings.timeout_seconds)),
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
                        max_width=max(self.settings.max_width, provider_width, request.width),
                        max_height=max(self.settings.max_height, provider_height, request.height),
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
                        cached_metadata = self.cache.set(cache_key, output_path.read_bytes(), metadata)
                        metadata = {**cached_metadata, "cache_hit": False, "current_task_asset": str(output_path)}
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
        if not providers:
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


def _validate_cached(path: Path, cached: dict, request: ImageGenerationRequest, settings: ImageGenerationSettings) -> dict:
    if not path.is_file():
        raise ValueError("missing cached image")
    data = path.read_bytes()
    import hashlib

    sha256 = hashlib.sha256(data).hexdigest()
    if cached.get("sha256") and cached["sha256"] != sha256:
        raise ValueError("cached image hash mismatch")
    info = validate_image_file(
        path,
        expected_mime="image/png",
        max_bytes=request.max_output_bytes,
        max_width=max(settings.max_width, request.width),
        max_height=max(settings.max_height, request.height),
    )
    return {**info, "sha256": sha256}


def _copy_or_link(source: Path, target: Path) -> None:
    try:
        if target.exists():
            target.unlink()
        target.hardlink_to(source)
    except Exception:
        copyfile(source, target)
