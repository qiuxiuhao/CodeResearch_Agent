from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.runtime import ImageGenerationRuntime, create_image_generation_runtime
from backend.app.llm.config import LLMSettings
from backend.app.llm.runtime import LLMRuntime, create_llm_runtime
from backend.app.settings.provider_settings import ProviderSettingsService
from backend.app.vision.config import VisionSettings
from backend.app.vision.runtime import VisionRuntime, create_vision_runtime


class AnalysisOptionsError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ResolvedAnalysisOptions(BaseModel):
    """JSON-safe task options; deliberately excludes provider configuration and secrets."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    analysis_mode: Literal["rule", "hybrid"]
    external_model_consent: bool
    text_llm_enabled: bool
    teaching_narrative_llm_enabled: bool
    vision_vlm_enabled: bool
    external_text_consent: bool
    external_vision_consent: bool
    teaching_diagrams_enabled: bool
    image_generation_enabled: bool
    teaching_review_vlm_enabled: bool
    external_image_consent: bool
    external_teaching_review_consent: bool
    structured_index_enabled: bool
    index_repository_identity: str | None
    structured_index_db_path: str

    def state_dump(self) -> dict[str, bool | str | None]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class ResolvedProviderSettings:
    llm: LLMSettings
    vision: VisionSettings
    image: ImageGenerationSettings


@dataclass(frozen=True)
class ProviderRuntimeContext:
    """Process-only runtimes. This type intentionally exposes no serialization method."""

    llm: LLMRuntime
    vision: VisionRuntime
    image: ImageGenerationRuntime


def resolve_analysis_options(
    *,
    analysis_mode: str | None = None,
    external_model_consent: bool = False,
    text_llm_enabled: bool | None = None,
    teaching_narrative_llm_enabled: bool | None = None,
    vision_vlm_enabled: bool | None = None,
    external_text_consent: bool | None = None,
    external_vision_consent: bool = False,
    teaching_diagrams_enabled: bool = True,
    image_generation_enabled: bool | None = None,
    external_image_consent: bool = False,
    teaching_review_vlm_enabled: bool | None = None,
    external_teaching_review_consent: bool = False,
    structured_index_enabled: bool | None = None,
    repository_key: str | None = None,
    structured_index_db_path: str | None = None,
    llm_settings: LLMSettings | None = None,
    vision_settings: VisionSettings | None = None,
    image_settings: ImageGenerationSettings | None = None,
) -> tuple[ResolvedAnalysisOptions, ResolvedProviderSettings]:
    llm = llm_settings or LLMSettings.from_env(
        analysis_mode, text_llm_enabled, teaching_narrative_llm_enabled
    )
    text_consent = external_model_consent if external_text_consent is None else external_text_consent
    if llm.text_llm_enabled and not text_consent:
        raise AnalysisOptionsError(
            "text_llm_enabled=true requires external_text_consent=true "
            "(legacy external_model_consent=true) before code is sent to external model providers."
        )
    if llm.teaching_narrative_llm_enabled and not text_consent:
        raise AnalysisOptionsError(
            "teaching_narrative_llm_enabled=true requires external_text_consent=true "
            "before teaching narrative data is sent to external model providers."
        )

    vision = vision_settings or VisionSettings.from_env(vision_vlm_enabled)
    if vision.enabled and not external_vision_consent:
        raise AnalysisOptionsError(
            "vision_vlm_enabled=true requires external_vision_consent=true before paper figures are sent to external model providers."
        )

    review_enabled = _resolve_teaching_review_enabled(
        teaching_review_vlm_enabled, external_teaching_review_consent
    )
    image = image_settings or ImageGenerationSettings.from_env(
        image_generation_enabled, external_image_consent, review_enabled
    )
    if image.enabled and not external_image_consent:
        raise AnalysisOptionsError(
            "image_generation_enabled=true requires external_image_consent=true before teaching diagram specs are sent to image providers."
        )
    if image.teaching_review_vlm_enabled and not image.enabled:
        raise AnalysisOptionsError(
            "teaching_review_vlm_enabled=true requires image_generation_enabled=true.", status_code=422
        )
    if image.teaching_review_vlm_enabled and not external_image_consent:
        raise AnalysisOptionsError(
            "teaching_review_vlm_enabled=true requires external_image_consent=true.", status_code=422
        )
    if image.teaching_review_vlm_enabled and not external_teaching_review_consent:
        raise AnalysisOptionsError(
            "teaching_review_vlm_enabled=true requires external_teaching_review_consent=true.", status_code=422
        )

    options = ResolvedAnalysisOptions(
        analysis_mode=llm.analysis_mode,
        external_model_consent=text_consent,
        text_llm_enabled=llm.text_llm_enabled,
        teaching_narrative_llm_enabled=llm.teaching_narrative_llm_enabled,
        vision_vlm_enabled=vision.enabled,
        external_text_consent=text_consent,
        external_vision_consent=external_vision_consent,
        teaching_diagrams_enabled=teaching_diagrams_enabled,
        image_generation_enabled=image.enabled,
        teaching_review_vlm_enabled=image.teaching_review_vlm_enabled,
        external_image_consent=external_image_consent,
        external_teaching_review_consent=external_teaching_review_consent,
        structured_index_enabled=(
            _bool_env("STRUCTURED_INDEX_ENABLED", False)
            if structured_index_enabled is None else structured_index_enabled
        ),
        index_repository_identity=repository_key,
        structured_index_db_path=(
            structured_index_db_path or os.getenv("STRUCTURED_INDEX_DB_PATH") or "data/structured_index.sqlite3"
        ),
    )
    return options, ResolvedProviderSettings(llm=llm, vision=vision, image=image)


def create_provider_runtime_context(
    settings: ResolvedProviderSettings,
    *,
    llm_runtime: LLMRuntime | None = None,
    vision_runtime: VisionRuntime | None = None,
    image_runtime: ImageGenerationRuntime | None = None,
) -> ProviderRuntimeContext:
    _validate_enabled_provider_base_urls(settings)
    return ProviderRuntimeContext(
        llm=llm_runtime or create_llm_runtime(settings.llm),
        vision=vision_runtime or create_vision_runtime(settings.vision),
        image=image_runtime or create_image_generation_runtime(settings.image),
    )


def _validate_enabled_provider_base_urls(settings: ResolvedProviderSettings) -> None:
    provider_ids: list[str] = []
    if settings.llm.text_llm_enabled or settings.llm.teaching_narrative_llm_enabled:
        provider_ids.extend(["deepseek", "qwen"])
    if settings.vision.enabled or settings.image.teaching_review_vlm_enabled:
        provider_ids.extend(["qwen_vl", "glm_v"])
    if settings.image.enabled:
        provider_ids.extend(["qwen_image", "seedream"])
    if provider_ids:
        ProviderSettingsService().validate_runtime_base_urls(provider_ids)


def _resolve_teaching_review_enabled(
    teaching_review_enabled: bool | None,
    teaching_review_consent: bool,
) -> bool | None:
    if teaching_review_enabled is not None:
        return teaching_review_enabled
    return None if teaching_review_consent else False


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
