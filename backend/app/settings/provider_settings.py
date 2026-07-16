from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.app.image_generation.config import ImageProviderSettings
from backend.app.image_generation.providers.qwen_image_provider import QwenImageProvider
from backend.app.image_generation.providers.seedream_provider import SeedreamProvider
from backend.app.image_generation.types import ImageGenerationRequest
from backend.app.llm.config import ProviderSettings as LLMProviderSettings
from backend.app.llm.providers.deepseek_provider import DeepSeekProvider
from backend.app.llm.providers.qwen_provider import QwenProvider
from backend.app.llm.types import ProviderRequest
from backend.app.schemas.provider_settings import (
    ProviderApiKeyDeleteRequest,
    ProviderPublicSettings,
    ProviderSettingsListResponse,
    ProviderSettingsUpdateRequest,
    ProviderTestResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from backend.app.settings.secret_store import (
    SecretStore,
    SecretStoreConflictError,
    looks_like_masked_key,
    masked_key,
)
from backend.app.settings.ssrf_guard import validate_base_url
from backend.app.vision.config import VisionProviderSettings
from backend.app.vision.providers.glm_v_provider import GLMVProvider
from backend.app.vision.providers.qwen_vl_provider import QwenVLProvider
from backend.app.vision.types import VisionRequest


@dataclass(frozen=True)
class FieldDefinition:
    env: str | None
    default: Any
    kind: str = "str"


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    group: str
    fields: dict[str, FieldDefinition]


PROVIDERS: dict[str, ProviderDefinition] = {
    "deepseek": ProviderDefinition("deepseek", "DeepSeek", "text_llm", {
        "enabled": FieldDefinition("DEEPSEEK_ENABLED", True, "bool"),
        "api_key": FieldDefinition("DEEPSEEK_API_KEY", "", "secret"),
        "base_url": FieldDefinition("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": FieldDefinition("DEEPSEEK_MODEL", "deepseek-chat"),
        "timeout_seconds": FieldDefinition("LLM_TIMEOUT_SECONDS", 45, "float"),
        "retry": FieldDefinition("LLM_MAX_RETRIES", 1, "int"),
        "max_output_tokens": FieldDefinition("LLM_MAX_OUTPUT_TOKENS", 1200, "int"),
    }),
    "qwen": ProviderDefinition("qwen", "Qwen", "text_llm", {
        "enabled": FieldDefinition("QWEN_ENABLED", True, "bool"),
        "api_key": FieldDefinition("QWEN_API_KEY", "", "secret"),
        "base_url": FieldDefinition("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": FieldDefinition("QWEN_MODEL", "qwen-plus"),
        "timeout_seconds": FieldDefinition("LLM_TIMEOUT_SECONDS", 45, "float"),
        "retry": FieldDefinition("LLM_MAX_RETRIES", 1, "int"),
        "max_output_tokens": FieldDefinition("LLM_MAX_OUTPUT_TOKENS", 1200, "int"),
    }),
    "qwen_vl": ProviderDefinition("qwen_vl", "Qwen-VL", "vision_vlm", {
        "enabled": FieldDefinition("QWEN_VL_ENABLED", True, "bool"),
        "api_key": FieldDefinition("QWEN_VL_API_KEY", "", "secret"),
        "base_url": FieldDefinition("QWEN_VL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": FieldDefinition("QWEN_VL_MODEL", "qwen-vl-plus"),
        "timeout_seconds": FieldDefinition("VLM_TIMEOUT_SECONDS", 45, "float"),
        "retry": FieldDefinition("VLM_MAX_RETRIES", 1, "int"),
        "max_output_tokens": FieldDefinition("VLM_MAX_OUTPUT_TOKENS", 1200, "int"),
        "supports_json_object": FieldDefinition("QWEN_VL_SUPPORTS_JSON_OBJECT", False, "bool"),
        "disable_thinking": FieldDefinition("QWEN_VL_DISABLE_THINKING", False, "bool"),
    }),
    "glm_v": ProviderDefinition("glm_v", "GLM Vision", "vision_vlm", {
        "enabled": FieldDefinition("GLM_V_ENABLED", True, "bool"),
        "api_key": FieldDefinition("GLM_V_API_KEY", "", "secret"),
        "base_url": FieldDefinition("GLM_V_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        "model": FieldDefinition("GLM_V_MODEL", "glm-4.5v"),
        "timeout_seconds": FieldDefinition("VLM_TIMEOUT_SECONDS", 45, "float"),
        "retry": FieldDefinition("VLM_MAX_RETRIES", 1, "int"),
        "max_output_tokens": FieldDefinition("VLM_MAX_OUTPUT_TOKENS", 1200, "int"),
        "supports_json_object": FieldDefinition("GLM_V_SUPPORTS_JSON_OBJECT", False, "bool"),
        "disable_thinking": FieldDefinition("GLM_V_DISABLE_THINKING", False, "bool"),
    }),
    "qwen_image": ProviderDefinition("qwen_image", "Qwen-Image", "image_generation", {
        "enabled": FieldDefinition("QWEN_IMAGE_ENABLED", True, "bool"),
        "api_key": FieldDefinition("QWEN_IMAGE_API_KEY", "", "secret"),
        "base_url": FieldDefinition("QWEN_IMAGE_BASE_URL", "https://dashscope.aliyuncs.com"),
        "model": FieldDefinition("QWEN_IMAGE_MODEL", ""),
        "timeout_seconds": FieldDefinition("IMAGE_GENERATION_TIMEOUT_SECONDS", 60, "float"),
        "retry": FieldDefinition(None, 0, "int"),
        "request_width": FieldDefinition("QWEN_IMAGE_REQUEST_WIDTH", 1280, "int"),
        "request_height": FieldDefinition("QWEN_IMAGE_REQUEST_HEIGHT", 720, "int"),
        "allowed_domains": FieldDefinition("QWEN_IMAGE_ALLOWED_DOMAINS", "dashscope.aliyuncs.com,aliyuncs.com,oss-cn-hangzhou.aliyuncs.com,oss-cn-beijing.aliyuncs.com,oss-cn-shanghai.aliyuncs.com,oss-cn-shenzhen.aliyuncs.com", "csv"),
        "endpoint_path": FieldDefinition("QWEN_IMAGE_ENDPOINT_PATH", "/api/v1/services/aigc/multimodal-generation/generation"),
        "workspace": FieldDefinition("QWEN_IMAGE_WORKSPACE", ""),
        "supports_async": FieldDefinition("QWEN_IMAGE_SUPPORTS_ASYNC", False, "bool"),
    }),
    "seedream": ProviderDefinition("seedream", "Seedream", "image_generation", {
        "enabled": FieldDefinition("SEEDREAM_ENABLED", True, "bool"),
        "api_key": FieldDefinition("SEEDREAM_API_KEY", "", "secret"),
        "base_url": FieldDefinition("SEEDREAM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "model": FieldDefinition("SEEDREAM_MODEL", ""),
        "timeout_seconds": FieldDefinition("IMAGE_GENERATION_TIMEOUT_SECONDS", 60, "float"),
        "retry": FieldDefinition(None, 0, "int"),
        "request_width": FieldDefinition("SEEDREAM_REQUEST_WIDTH", 1280, "int"),
        "request_height": FieldDefinition("SEEDREAM_REQUEST_HEIGHT", 720, "int"),
        "allowed_domains": FieldDefinition("SEEDREAM_ALLOWED_DOMAINS", "ark.cn-beijing.volces.com", "csv"),
        "endpoint_path": FieldDefinition("SEEDREAM_ENDPOINT_PATH", "/images/generations"),
        "workspace": FieldDefinition(None, ""),
        "supports_async": FieldDefinition("SEEDREAM_SUPPORTS_ASYNC", False, "bool"),
    }),
}


class ProviderSettingsService:
    def __init__(self, store: SecretStore | None = None) -> None:
        self.store = store or SecretStore()

    def list_public_settings(self) -> ProviderSettingsListResponse:
        revision = self.store.current_revision()
        warnings: list[str] = []
        providers = []
        for provider_id in PROVIDERS:
            try:
                providers.append(self.get_public_settings(provider_id, revision=revision))
            except Exception:
                warnings.append(f"{provider_id}: settings unavailable")
        return ProviderSettingsListResponse(revision=revision, providers=providers, warnings=warnings)

    def get_public_settings(self, provider_id: str, *, revision: int | None = None) -> ProviderPublicSettings:
        definition = _definition(provider_id)
        values, source = self._resolved_values(provider_id)
        key = str(values.pop("api_key", "") or "")
        key_source = source.get("api_key")
        configured = bool(key.strip() and str(values.get("model", "")).strip() and str(values.get("base_url", "")).strip())
        fields = {key_name: value for key_name, value in values.items() if key_name != "api_key"}
        warnings = []
        if fields.get("supports_async"):
            warnings.append("v1.3.3 only supports synchronous image generation; async provider mode is disabled.")
        if key_source == "Environment":
            warnings.append("API key comes from Environment and cannot be deleted from the UI.")
        return ProviderPublicSettings(
            id=provider_id,
            display_name=definition.display_name,
            group=definition.group,  # type: ignore[arg-type]
            enabled=bool(fields.get("enabled", True)),
            configured=configured,
            masked_key=masked_key(key),
            revision=self.store.current_revision() if revision is None else revision,
            source={key_name: value for key_name, value in source.items() if key_name != "api_key"},
            fields=fields,
            warnings=warnings,
        )

    def runtime_provider_values(self, provider_id: str) -> dict[str, Any]:
        values, _source = self._resolved_values(provider_id)
        if values.get("enabled") is False:
            values["api_key"] = ""
        return values

    def validate(
        self,
        provider_id: str,
        request: ProviderValidateRequest | ProviderSettingsUpdateRequest,
        *,
        require_configured_key: bool = False,
    ) -> ProviderValidateResponse:
        _definition(provider_id)
        values = request.model_dump(exclude_unset=True)
        resolved_values, _source = self._resolved_values(provider_id)
        effective_values = {**resolved_values, **{key: value for key, value in values.items() if value is not None}}
        errors: list[str] = []
        warnings: list[str] = []
        api_key = str(values.get("api_key") or resolved_values.get("api_key") or "")
        if values.get("api_key") and looks_like_masked_key(str(values["api_key"])):
            errors.append("masked_key is display-only and cannot be used as api_key.")
        if require_configured_key and bool(effective_values.get("enabled", True)) and not api_key.strip():
            errors.append("API Key is required before this provider can be used.")
        model = values.get("model")
        if model is not None and (not str(model).strip() or len(str(model)) > 120):
            errors.append("model must be non-empty and at most 120 characters.")
        if require_configured_key and not str(effective_values.get("model", "")).strip():
            errors.append("model is required before this provider can be used.")
        if require_configured_key and not str(effective_values.get("base_url", "")).strip():
            errors.append("base_url is required before this provider can be used.")
        timeout = values.get("timeout_seconds")
        if timeout is not None and not (1 <= float(timeout) <= 600):
            errors.append("timeout_seconds must be between 1 and 600.")
        retry = values.get("retry")
        if retry is not None and not (0 <= int(retry) <= 5):
            errors.append("retry must be between 0 and 5.")
        for name in ("request_width", "request_height"):
            value = values.get(name)
            if value is not None and not (64 <= int(value) <= 4096):
                errors.append(f"{name} must be between 64 and 4096.")
        domains = values.get("allowed_domains")
        if domains is not None and any(not _valid_hostname(item) for item in domains):
            errors.append("allowed_domains contains an invalid hostname.")
        if values.get("supports_async"):
            warnings.append("Async image task polling is reserved and not enabled in v1.3.3.")
        base_url = values.get("base_url")
        if base_url:
            try:
                validate_base_url(
                    provider_id,
                    str(base_url),
                    allow_custom_base_url=bool(values.get("allow_custom_base_url")),
                    allow_local_endpoint=bool(values.get("allow_local_endpoint")),
                    resolve_dns=False,
                )
            except ValueError as exc:
                errors.append(str(exc))
        return ProviderValidateResponse(ok=not errors, errors=errors, warnings=warnings)

    def save(self, provider_id: str, request: ProviderSettingsUpdateRequest) -> ProviderPublicSettings:
        _definition(provider_id)
        if request.api_key and looks_like_masked_key(request.api_key):
            raise ValueError("masked_key is display-only and cannot be saved as api_key.")
        validation = self.validate(provider_id, request, require_configured_key=False)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))
        config = {
            key: value
            for key, value in request.model_dump(exclude_unset=True).items()
            if key not in {"expected_revision", "api_key"}
        }
        try:
            data = self.store.update_provider(
                provider_id,
                config=config,
                api_key=request.api_key.strip() if request.api_key else None,
                expected_revision=request.expected_revision,
            )
        except SecretStoreConflictError:
            raise
        return self.get_public_settings(provider_id, revision=int(data.get("revision", 0)))

    def delete_api_key(self, provider_id: str, request: ProviderApiKeyDeleteRequest) -> ProviderPublicSettings:
        _definition(provider_id)
        try:
            data = self.store.delete_api_key(provider_id, expected_revision=request.expected_revision)
        except SecretStoreConflictError:
            raise
        return self.get_public_settings(provider_id, revision=int(data.get("revision", 0)))

    def test_provider(self, provider_id: str, *, confirm_cost: bool) -> ProviderTestResponse:
        if not confirm_cost:
            raise ValueError("confirm_cost=true is required before provider test.")
        values = self.runtime_provider_values(provider_id)
        validation = self.validate(provider_id, ProviderValidateRequest(
            base_url=values.get("base_url"),
            model=values.get("model"),
            api_key=values.get("api_key"),
            timeout_seconds=values.get("timeout_seconds"),
            retry=values.get("retry"),
            request_width=values.get("request_width"),
            request_height=values.get("request_height"),
            allowed_domains=values.get("allowed_domains"),
            endpoint_path=values.get("endpoint_path"),
            allow_custom_base_url=bool(values.get("allow_custom_base_url")),
            allow_local_endpoint=bool(values.get("allow_local_endpoint")),
        ), require_configured_key=True)
        if not validation.ok:
            return ProviderTestResponse(success=False, provider=provider_id, model=values.get("model"), warning=validation.errors[0])
        try:
            validate_base_url(
                provider_id,
                str(values.get("base_url", "")),
                allow_custom_base_url=bool(values.get("allow_custom_base_url")),
                allow_local_endpoint=bool(values.get("allow_local_endpoint")),
                resolve_dns=True,
            )
            started = time.monotonic()
            self._send_minimal_test(provider_id, values)
            latency_ms = int((time.monotonic() - started) * 1000)
            return ProviderTestResponse(success=True, provider=provider_id, model=values.get("model"), latency_ms=latency_ms)
        except Exception as exc:
            return ProviderTestResponse(success=False, provider=provider_id, model=values.get("model"), warning=type(exc).__name__)

    def _resolved_values(self, provider_id: str) -> tuple[dict[str, Any], dict[str, str]]:
        definition = _definition(provider_id)
        ui_config = self.store.provider_config(provider_id)
        values: dict[str, Any] = {}
        source: dict[str, str] = {}
        for field_name, field_def in definition.fields.items():
            if field_name == "api_key":
                ui_key = self.store.provider_api_key(provider_id)
                if ui_key:
                    values[field_name] = ui_key
                    source[field_name] = "UI"
                    continue
            if field_name in ui_config:
                values[field_name] = _coerce(ui_config[field_name], field_def.kind)
                source[field_name] = "UI"
            elif field_def.env and os.getenv(field_def.env) not in (None, ""):
                values[field_name] = _coerce(os.getenv(field_def.env), field_def.kind)
                source[field_name] = "Environment"
            else:
                values[field_name] = _coerce(field_def.default, field_def.kind)
                source[field_name] = "Default"
        for extra_name in ("allow_custom_base_url", "allow_local_endpoint"):
            if extra_name in ui_config:
                values[extra_name] = _coerce(ui_config[extra_name], "bool")
                source[extra_name] = "UI"
            else:
                values[extra_name] = False
                source[extra_name] = "Default"
        return values, source

    def _send_minimal_test(self, provider_id: str, values: dict[str, Any]) -> None:
        if provider_id in {"deepseek", "qwen"}:
            provider_settings = LLMProviderSettings(
                name=provider_id,
                api_key=str(values.get("api_key", "")),
                base_url=str(values.get("base_url", "")),
                model=str(values.get("model", "")),
            )
            provider = DeepSeekProvider(provider_settings, float(values.get("timeout_seconds", 45))) if provider_id == "deepseek" else QwenProvider(provider_settings, float(values.get("timeout_seconds", 45)))
            provider.generate(ProviderRequest(
                task_type="provider_test",
                system_prompt="Return JSON matching the schema.",
                input_payload={"test": "ping"},
                response_model=_ProviderTextTest,
                max_output_tokens=64,
            ))
            return
        if provider_id in {"qwen_vl", "glm_v"}:
            provider_settings = VisionProviderSettings(
                name=provider_id,
                api_key=str(values.get("api_key", "")),
                base_url=str(values.get("base_url", "")),
                model=str(values.get("model", "")),
                supports_json_object=bool(values.get("supports_json_object", False)),
                disable_thinking=bool(values.get("disable_thinking", False)),
            )
            provider = QwenVLProvider(provider_settings, float(values.get("timeout_seconds", 45))) if provider_id == "qwen_vl" else GLMVProvider(provider_settings, float(values.get("timeout_seconds", 45)))
            provider.analyze_figure(VisionRequest(
                context_id="provider_test",
                system_prompt="Return JSON matching the schema.",
                input_payload={"test": "ping"},
                image_bytes=_ONE_PIXEL_PNG,
                mime_type="image/png",
                response_model=_ProviderTextTest,
                max_output_tokens=64,
            ))
            return
        provider_settings = ImageProviderSettings(
            name=provider_id,
            api_key=str(values.get("api_key", "")),
            base_url=str(values.get("base_url", "")),
            model=str(values.get("model", "")),
            allowed_domains=list(values.get("allowed_domains") or []),
            endpoint_path=str(values.get("endpoint_path", "")),
            workspace=str(values.get("workspace", "")),
            supports_async=bool(values.get("supports_async", False)),
            request_width=int(values.get("request_width", 512)),
            request_height=int(values.get("request_height", 512)),
        )
        provider = QwenImageProvider(provider_settings, float(values.get("timeout_seconds", 60))) if provider_id == "qwen_image" else SeedreamProvider(provider_settings, float(values.get("timeout_seconds", 60)))
        with tempfile.TemporaryDirectory(prefix="coderesearch_provider_test_") as directory:
            provider.generate_image(ImageGenerationRequest(
                diagram_id="provider_test",
                public_spec={"public_spec_hash": "0" * 64, "modules": []},
                prompt_version="provider-test",
                schema_version="1.3.3",
                width=int(values.get("request_width", 512)),
                height=int(values.get("request_height", 512)),
                mime_type="image/png",
                max_output_bytes=1024 * 1024,
                output_dir=Path(directory),
            ))


class _ProviderTextTest(BaseModel):
    message: str | None = None


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00\x00"
    b"\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _definition(provider_id: str) -> ProviderDefinition:
    if provider_id not in PROVIDERS:
        raise ValueError("Unknown provider id.")
    return PROVIDERS[provider_id]


def _coerce(value: Any, kind: str) -> Any:
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "csv":
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return [item.strip().lower() for item in str(value).split(",") if item.strip()]
    return str(value)


def _valid_hostname(value: str) -> bool:
    if not value or len(value) > 253 or "/" in value or ":" in value:
        return False
    labels = value.strip(".").split(".")
    return all(label and len(label) <= 63 and label.replace("-", "").isalnum() for label in labels)
