from __future__ import annotations

import os

from pydantic import BaseModel, Field

from backend.app.settings.provider_registry import resolve_provider_values


class ImageProviderSettings(BaseModel):
    name: str
    api_key: str = ""
    base_url: str
    model: str
    timeout_seconds: float = Field(default=60, ge=1, le=600)
    max_retries: int = Field(default=0, ge=0, le=5)
    allowed_domains: list[str] = Field(default_factory=list)
    endpoint_path: str = ""
    workspace: str = ""
    request_width: int = Field(default=1280, ge=64, le=4096)
    request_height: int = Field(default=720, ge=64, le=4096)
    min_request_width: int = Field(default=64, ge=1, le=4096)
    max_request_width: int = Field(default=2048, ge=64, le=8192)
    min_request_height: int = Field(default=64, ge=1, le=4096)
    max_request_height: int = Field(default=2048, ge=64, le=8192)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.model.strip() and self.base_url.strip())

    def validate_request_size(self) -> tuple[int, int]:
        width = self.request_width
        height = self.request_height
        if not (self.min_request_width <= width <= self.max_request_width):
            raise ValueError(f"{self.name} request width is outside supported bounds.")
        if not (self.min_request_height <= height <= self.max_request_height):
            raise ValueError(f"{self.name} request height is outside supported bounds.")
        return width, height


class ImageGenerationSettings(BaseModel):
    enabled: bool = False
    external_image_consent: bool = False
    teaching_review_vlm_enabled: bool = False
    qwen_image: ImageProviderSettings
    seedream: ImageProviderSettings
    timeout_seconds: float = Field(default=60, ge=1, le=600)
    max_retries: int = Field(default=0, ge=0, le=5)
    max_provider_requests: int = Field(default=8, ge=0, le=1000)
    max_concurrency: int = Field(default=1, ge=1, le=1)
    max_single_image_bytes: int = Field(default=10_485_760, ge=1024)
    max_width: int = Field(default=1536, ge=64, le=8192)
    max_height: int = Field(default=1536, ge=64, le=8192)
    cache_enabled: bool = True
    cache_path: str = "data/image_generation_cache.sqlite3"
    cache_asset_root: str = "data/image_generation_cache"
    prompt_version: str = "1.3.3"
    schema_version: str = "1.3.3"
    teaching_plan_max_llm_requests: int = Field(default=4, ge=0, le=1000)
    teaching_review_max_provider_requests: int = Field(default=8, ge=0, le=1000)

    @classmethod
    def from_env(
        cls,
        enabled: bool | None = None,
        external_image_consent: bool = False,
        teaching_review_vlm_enabled: bool | None = None,
    ) -> "ImageGenerationSettings":
        qwen_values, _ = _runtime_provider_bundle("qwen_image")
        seedream_values, _ = _runtime_provider_bundle("seedream")
        return cls(
            enabled=_bool_env("IMAGE_GENERATION_ENABLED", False) if enabled is None else enabled,
            external_image_consent=external_image_consent,
            teaching_review_vlm_enabled=_bool_env("TEACHING_REVIEW_VLM_ENABLED", False)
            if teaching_review_vlm_enabled is None else teaching_review_vlm_enabled,
            qwen_image=ImageProviderSettings(
                name="qwen_image",
                api_key=str(qwen_values["api_key"]),
                base_url=str(qwen_values["base_url"]),
                model=str(qwen_values["model"]),
                timeout_seconds=float(qwen_values["timeout_seconds"]),
                max_retries=int(qwen_values["retry"]),
                allowed_domains=list(qwen_values["allowed_domains"]),
                endpoint_path=str(qwen_values["endpoint_path"]),
                workspace=str(qwen_values["workspace"]),
                request_width=int(qwen_values["request_width"]),
                request_height=int(qwen_values["request_height"]),
                min_request_width=256,
                min_request_height=256,
                max_request_width=2048,
                max_request_height=2048,
            ),
            seedream=ImageProviderSettings(
                name="seedream",
                api_key=str(seedream_values["api_key"]),
                base_url=str(seedream_values["base_url"]),
                model=str(seedream_values["model"]),
                timeout_seconds=float(seedream_values["timeout_seconds"]),
                max_retries=int(seedream_values["retry"]),
                allowed_domains=list(seedream_values["allowed_domains"]),
                endpoint_path=str(seedream_values["endpoint_path"]),
                request_width=int(seedream_values["request_width"]),
                request_height=int(seedream_values["request_height"]),
                min_request_width=256,
                min_request_height=256,
                max_request_width=4096,
                max_request_height=4096,
            ),
            timeout_seconds=_float_env("IMAGE_GENERATION_TIMEOUT_SECONDS", 60),
            max_retries=_int_env("IMAGE_GENERATION_MAX_RETRIES", 0),
            max_provider_requests=_int_env("TEACHING_IMAGE_MAX_PROVIDER_REQUESTS", _int_env("IMAGE_GENERATION_MAX_PROVIDER_REQUESTS", 8)),
            max_concurrency=1,
            max_single_image_bytes=_int_env("IMAGE_GENERATION_MAX_SINGLE_IMAGE_BYTES", 10_485_760),
            max_width=_int_env("IMAGE_GENERATION_MAX_WIDTH", 1536),
            max_height=_int_env("IMAGE_GENERATION_MAX_HEIGHT", 1536),
            cache_enabled=_bool_env("IMAGE_GENERATION_CACHE_ENABLED", True),
            cache_path=os.getenv("IMAGE_GENERATION_CACHE_PATH", "data/image_generation_cache.sqlite3"),
            cache_asset_root=os.getenv("IMAGE_GENERATION_CACHE_ASSET_ROOT", "data/image_generation_cache"),
            prompt_version=os.getenv("IMAGE_GENERATION_PROMPT_VERSION", "1.3.3"),
            schema_version=os.getenv("IMAGE_GENERATION_SCHEMA_VERSION", "1.3.3"),
            teaching_plan_max_llm_requests=_int_env("TEACHING_PLAN_MAX_LLM_REQUESTS", 4),
            teaching_review_max_provider_requests=_int_env("TEACHING_REVIEW_MAX_PROVIDER_REQUESTS", 8),
        )

    def public_config(self) -> dict:
        return {
            "default_image_generation_enabled": self.enabled,
            "default_teaching_review_vlm_enabled": self.teaching_review_vlm_enabled,
            "max_provider_requests": self.max_provider_requests,
            "teaching_narrative_max_provider_requests": self.teaching_plan_max_llm_requests,
            "teaching_review_max_provider_requests": self.teaching_review_max_provider_requests,
            "max_concurrency": self.max_concurrency,
            "providers": {
                "qwen_image": {"configured": self.qwen_image.configured, "model": self.qwen_image.model},
                "seedream": {"configured": self.seedream.configured, "model": self.seedream.model},
            },
            "external_image_notice": (
                "启用 AI 教学图视觉层后，脱敏后的 TeachingDiagramSpec 可能发送到外部图片生成服务商，"
                "并可能产生费用；不会发送完整源码、完整仓库或完整论文。"
            ),
        }


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _runtime_provider_bundle(provider_id: str) -> tuple[dict[str, object], dict[str, str]]:
    return resolve_provider_values(provider_id)
