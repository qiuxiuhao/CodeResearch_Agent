from __future__ import annotations

import os

from pydantic import BaseModel, Field


class ImageProviderSettings(BaseModel):
    name: str
    api_key: str = ""
    base_url: str
    model: str
    allowed_domains: list[str] = Field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())


class ImageGenerationSettings(BaseModel):
    enabled: bool = False
    external_image_consent: bool = False
    teaching_review_vlm_enabled: bool = False
    qwen_image: ImageProviderSettings
    seedream: ImageProviderSettings
    timeout_seconds: float = Field(default=60, ge=1, le=600)
    max_provider_requests: int = Field(default=8, ge=0, le=1000)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_single_image_bytes: int = Field(default=10_485_760, ge=1024)
    max_width: int = Field(default=1536, ge=64, le=8192)
    max_height: int = Field(default=1536, ge=64, le=8192)
    cache_enabled: bool = True
    cache_path: str = "data/image_generation_cache.sqlite3"
    cache_asset_root: str = "data/image_generation_cache"
    prompt_version: str = "1.3.0"
    schema_version: str = "1.3.0"
    task_max_poll_seconds: float = Field(default=90, ge=1, le=3600)
    task_poll_interval_seconds: float = Field(default=2, ge=0.1, le=120)
    task_max_poll_attempts: int = Field(default=45, ge=1, le=1000)
    teaching_plan_max_llm_requests: int = Field(default=4, ge=0, le=1000)
    teaching_review_max_provider_requests: int = Field(default=8, ge=0, le=1000)

    @classmethod
    def from_env(
        cls,
        enabled: bool | None = None,
        external_image_consent: bool = False,
        teaching_review_vlm_enabled: bool | None = None,
    ) -> "ImageGenerationSettings":
        return cls(
            enabled=_bool_env("IMAGE_GENERATION_ENABLED", False) if enabled is None else enabled,
            external_image_consent=external_image_consent,
            teaching_review_vlm_enabled=_bool_env("TEACHING_REVIEW_VLM_ENABLED", False)
            if teaching_review_vlm_enabled is None else teaching_review_vlm_enabled,
            qwen_image=ImageProviderSettings(
                name="qwen_image",
                api_key=os.getenv("QWEN_IMAGE_API_KEY", ""),
                base_url=os.getenv("QWEN_IMAGE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                model=os.getenv("QWEN_IMAGE_MODEL", "qwen-image"),
                allowed_domains=_csv_env("QWEN_IMAGE_ALLOWED_DOMAINS", "dashscope.aliyuncs.com"),
            ),
            seedream=ImageProviderSettings(
                name="seedream",
                api_key=os.getenv("SEEDREAM_API_KEY", ""),
                base_url=os.getenv("SEEDREAM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
                model=os.getenv("SEEDREAM_MODEL", "seedream"),
                allowed_domains=_csv_env("SEEDREAM_ALLOWED_DOMAINS", "ark.cn-beijing.volces.com"),
            ),
            timeout_seconds=_float_env("IMAGE_GENERATION_TIMEOUT_SECONDS", 60),
            max_provider_requests=_int_env("TEACHING_IMAGE_MAX_PROVIDER_REQUESTS", _int_env("IMAGE_GENERATION_MAX_PROVIDER_REQUESTS", 8)),
            max_concurrency=_int_env("IMAGE_GENERATION_MAX_CONCURRENCY", 2),
            max_single_image_bytes=_int_env("IMAGE_GENERATION_MAX_SINGLE_IMAGE_BYTES", 10_485_760),
            max_width=_int_env("IMAGE_GENERATION_MAX_WIDTH", 1536),
            max_height=_int_env("IMAGE_GENERATION_MAX_HEIGHT", 1536),
            cache_enabled=_bool_env("IMAGE_GENERATION_CACHE_ENABLED", True),
            cache_path=os.getenv("IMAGE_GENERATION_CACHE_PATH", "data/image_generation_cache.sqlite3"),
            cache_asset_root=os.getenv("IMAGE_GENERATION_CACHE_ASSET_ROOT", "data/image_generation_cache"),
            prompt_version=os.getenv("IMAGE_GENERATION_PROMPT_VERSION", "1.3.0"),
            schema_version=os.getenv("IMAGE_GENERATION_SCHEMA_VERSION", "1.3.0"),
            task_max_poll_seconds=_float_env("IMAGE_TASK_MAX_POLL_SECONDS", 90),
            task_poll_interval_seconds=_float_env("IMAGE_TASK_POLL_INTERVAL_SECONDS", 2),
            task_max_poll_attempts=_int_env("IMAGE_TASK_MAX_POLL_ATTEMPTS", 45),
            teaching_plan_max_llm_requests=_int_env("TEACHING_PLAN_MAX_LLM_REQUESTS", 4),
            teaching_review_max_provider_requests=_int_env("TEACHING_REVIEW_MAX_PROVIDER_REQUESTS", 8),
        )

    def public_config(self) -> dict:
        return {
            "default_image_generation_enabled": self.enabled,
            "default_teaching_review_vlm_enabled": self.teaching_review_vlm_enabled,
            "max_provider_requests": self.max_provider_requests,
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


def _csv_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip().lower() for item in value.split(",") if item.strip()]
