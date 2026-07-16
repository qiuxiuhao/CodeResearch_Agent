from __future__ import annotations

import os

from pydantic import BaseModel, Field

from backend.app.config.pdf_safety import PDFSafetySettings


class VisionProviderSettings(BaseModel):
    name: str
    api_key: str = ""
    base_url: str
    model: str
    supports_json_object: bool = False
    disable_thinking: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())


class VisionSettings(BaseModel):
    enabled: bool = False
    qwen_vl: VisionProviderSettings
    glm_v: VisionProviderSettings
    timeout_seconds: float = Field(default=45, ge=1, le=300)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_figure_analyses: int = Field(default=5, ge=0, le=100)
    max_provider_requests: int = Field(default=10, ge=0, le=1000)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_single_image_bytes: int = Field(default=10_485_760, ge=1024)
    max_total_image_bytes: int = Field(default=31_457_280, ge=1024)
    max_image_width: int = Field(default=4096, ge=64, le=16384)
    max_image_height: int = Field(default=4096, ge=64, le=16384)
    max_output_tokens: int = Field(default=1200, ge=128, le=16000)
    cache_enabled: bool = True
    cache_path: str = "data/vlm_figure_cache.sqlite3"
    prompt_version: str = "1.2.0"
    schema_version: str = "1.2.3"
    paper_max_file_bytes: int = Field(default=52_428_800, ge=1024)
    paper_max_pages: int = Field(default=100, ge=1, le=5000)
    paper_max_image_objects: int = Field(default=500, ge=0, le=100000)
    paper_max_figure_candidates: int = Field(default=50, ge=0, le=10000)
    paper_max_original_asset_bytes: int = Field(default=104_857_600, ge=0)
    paper_max_single_asset_bytes: int = Field(default=20_971_520, ge=0)
    paper_max_render_pixels: int = Field(default=16_000_000, ge=10_000)
    paper_max_drawing_paths_per_page: int = Field(default=5000, ge=0, le=1_000_000)
    paper_extraction_timeout_seconds: float = Field(default=60, ge=1, le=3600)
    render_dpi: int = Field(default=144, ge=36, le=600)

    @classmethod
    def from_env(cls, enabled: bool | None = None) -> "VisionSettings":
        pdf_safety = PDFSafetySettings.from_env()
        qwen_values = _runtime_provider_values("qwen_vl")
        glm_values = _runtime_provider_values("glm_v")
        return cls(
            enabled=_bool_env("VISION_VLM_ENABLED", False) if enabled is None else enabled,
            qwen_vl=VisionProviderSettings(
                name="qwen_vl", api_key=qwen_values.get("api_key", os.getenv("QWEN_VL_API_KEY", "")),
                base_url=qwen_values.get("base_url", os.getenv("QWEN_VL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")),
                model=qwen_values.get("model", os.getenv("QWEN_VL_MODEL", "qwen-vl-plus")),
                supports_json_object=_bool_env("QWEN_VL_SUPPORTS_JSON_OBJECT", False),
                disable_thinking=_bool_env("QWEN_VL_DISABLE_THINKING", False),
            ),
            glm_v=VisionProviderSettings(
                name="glm_v", api_key=glm_values.get("api_key", os.getenv("GLM_V_API_KEY", "")),
                base_url=glm_values.get("base_url", os.getenv("GLM_V_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")),
                model=glm_values.get("model", os.getenv("GLM_V_MODEL", "glm-4.5v")),
                supports_json_object=_bool_env("GLM_V_SUPPORTS_JSON_OBJECT", False),
                disable_thinking=_bool_env("GLM_V_DISABLE_THINKING", False),
            ),
            timeout_seconds=_float_env("VLM_TIMEOUT_SECONDS", 45),
            max_retries=_int_env("VLM_MAX_RETRIES", 1),
            max_figure_analyses=_int_env("VLM_MAX_FIGURE_ANALYSES", 5),
            max_provider_requests=_int_env("VLM_MAX_PROVIDER_REQUESTS", 10),
            max_concurrency=_int_env("VLM_MAX_CONCURRENCY", 2),
            max_single_image_bytes=_int_env("VLM_MAX_SINGLE_IMAGE_BYTES", 10_485_760),
            max_total_image_bytes=_int_env("VLM_MAX_TOTAL_IMAGE_BYTES", 31_457_280),
            max_image_width=_int_env("VLM_MAX_IMAGE_WIDTH", 4096),
            max_image_height=_int_env("VLM_MAX_IMAGE_HEIGHT", 4096),
            max_output_tokens=_int_env("VLM_MAX_OUTPUT_TOKENS", 1200),
            cache_enabled=_bool_env("VLM_CACHE_ENABLED", True),
            cache_path=os.getenv("VLM_CACHE_PATH", "data/vlm_figure_cache.sqlite3"),
            prompt_version=os.getenv("VLM_PROMPT_VERSION", "1.2.0"),
            schema_version=os.getenv("VLM_SCHEMA_VERSION", "1.2.3"),
            paper_max_file_bytes=pdf_safety.max_file_bytes,
            paper_max_pages=pdf_safety.max_pages,
            paper_max_image_objects=_int_env("PAPER_MAX_IMAGE_OBJECTS", 500),
            paper_max_figure_candidates=_int_env("PAPER_MAX_FIGURE_CANDIDATES", 50),
            paper_max_original_asset_bytes=_int_env("PAPER_MAX_ORIGINAL_ASSET_BYTES", 104_857_600),
            paper_max_single_asset_bytes=_int_env("PAPER_MAX_SINGLE_ASSET_BYTES", 20_971_520),
            paper_max_render_pixels=_int_env("PAPER_MAX_RENDER_PIXELS", 16_000_000),
            paper_max_drawing_paths_per_page=_int_env("PAPER_MAX_DRAWING_PATHS_PER_PAGE", 5000),
            paper_extraction_timeout_seconds=_float_env("PAPER_EXTRACTION_TIMEOUT_SECONDS", 60),
            render_dpi=_int_env("PAPER_FIGURE_RENDER_DPI", 144),
        )

    def public_config(self) -> dict:
        return {
            "default_vision_vlm_enabled": self.enabled,
            "max_figure_analyses": self.max_figure_analyses,
            "max_provider_requests": self.max_provider_requests,
            "max_concurrency": self.max_concurrency,
            "providers": {
                "qwen_vl": {"configured": self.qwen_vl.configured, "model": self.qwen_vl.model},
                "glm_v": {"configured": self.glm_v.configured, "model": self.glm_v.model},
            },
            "external_vision_notice": (
                "筛选并渲染后的论文 Figure、图注及相关论文结构化信息可能发送给第三方视觉模型服务商，"
                "并可能产生费用；不会发送整个 PDF。"
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


def _runtime_provider_values(provider_id: str) -> dict[str, str]:
    try:
        from backend.app.settings.provider_settings import ProviderSettingsService

        return ProviderSettingsService().runtime_provider_values(provider_id)
    except Exception:
        return {}
