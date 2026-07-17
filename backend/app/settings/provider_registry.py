from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any

from backend.app.settings.secret_store import SecretStore


LOGGER = logging.getLogger(__name__)
_INVALID = object()


@dataclass(frozen=True)
class FieldDefinition:
    env: str | tuple[str, ...] | None
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
        "timeout_seconds": FieldDefinition(("DEEPSEEK_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS"), 45, "float"),
        "retry": FieldDefinition(("DEEPSEEK_MAX_RETRIES", "LLM_MAX_RETRIES"), 1, "int"),
        "max_output_tokens": FieldDefinition(("DEEPSEEK_MAX_OUTPUT_TOKENS", "LLM_MAX_OUTPUT_TOKENS"), 1200, "int"),
    }),
    "qwen": ProviderDefinition("qwen", "Qwen", "text_llm", {
        "enabled": FieldDefinition("QWEN_ENABLED", True, "bool"),
        "api_key": FieldDefinition("QWEN_API_KEY", "", "secret"),
        "base_url": FieldDefinition("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": FieldDefinition("QWEN_MODEL", "qwen-plus"),
        "timeout_seconds": FieldDefinition(("QWEN_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS"), 45, "float"),
        "retry": FieldDefinition(("QWEN_MAX_RETRIES", "LLM_MAX_RETRIES"), 1, "int"),
        "max_output_tokens": FieldDefinition(("QWEN_MAX_OUTPUT_TOKENS", "LLM_MAX_OUTPUT_TOKENS"), 1200, "int"),
    }),
    "qwen_vl": ProviderDefinition("qwen_vl", "Qwen-VL", "vision_vlm", {
        "enabled": FieldDefinition("QWEN_VL_ENABLED", True, "bool"),
        "api_key": FieldDefinition("QWEN_VL_API_KEY", "", "secret"),
        "base_url": FieldDefinition("QWEN_VL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": FieldDefinition("QWEN_VL_MODEL", "qwen-vl-plus"),
        "timeout_seconds": FieldDefinition(("QWEN_VL_TIMEOUT_SECONDS", "VLM_TIMEOUT_SECONDS"), 45, "float"),
        "retry": FieldDefinition(("QWEN_VL_MAX_RETRIES", "VLM_MAX_RETRIES"), 1, "int"),
        "max_output_tokens": FieldDefinition(("QWEN_VL_MAX_OUTPUT_TOKENS", "VLM_MAX_OUTPUT_TOKENS"), 1200, "int"),
        "supports_json_object": FieldDefinition("QWEN_VL_SUPPORTS_JSON_OBJECT", False, "bool"),
        "disable_thinking": FieldDefinition("QWEN_VL_DISABLE_THINKING", False, "bool"),
    }),
    "glm_v": ProviderDefinition("glm_v", "GLM Vision", "vision_vlm", {
        "enabled": FieldDefinition("GLM_V_ENABLED", True, "bool"),
        "api_key": FieldDefinition("GLM_V_API_KEY", "", "secret"),
        "base_url": FieldDefinition("GLM_V_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        "model": FieldDefinition("GLM_V_MODEL", "glm-4.5v"),
        "timeout_seconds": FieldDefinition(("GLM_V_TIMEOUT_SECONDS", "VLM_TIMEOUT_SECONDS"), 45, "float"),
        "retry": FieldDefinition(("GLM_V_MAX_RETRIES", "VLM_MAX_RETRIES"), 1, "int"),
        "max_output_tokens": FieldDefinition(("GLM_V_MAX_OUTPUT_TOKENS", "VLM_MAX_OUTPUT_TOKENS"), 1200, "int"),
        "supports_json_object": FieldDefinition("GLM_V_SUPPORTS_JSON_OBJECT", False, "bool"),
        "disable_thinking": FieldDefinition("GLM_V_DISABLE_THINKING", False, "bool"),
    }),
    "qwen_image": ProviderDefinition("qwen_image", "Qwen-Image", "image_generation", {
        "enabled": FieldDefinition("QWEN_IMAGE_ENABLED", True, "bool"),
        "api_key": FieldDefinition("QWEN_IMAGE_API_KEY", "", "secret"),
        "base_url": FieldDefinition("QWEN_IMAGE_BASE_URL", "https://dashscope.aliyuncs.com"),
        "model": FieldDefinition("QWEN_IMAGE_MODEL", ""),
        "timeout_seconds": FieldDefinition(("QWEN_IMAGE_TIMEOUT_SECONDS", "IMAGE_GENERATION_TIMEOUT_SECONDS"), 60, "float"),
        "retry": FieldDefinition(("QWEN_IMAGE_MAX_RETRIES", "IMAGE_GENERATION_MAX_RETRIES"), 0, "int"),
        "request_width": FieldDefinition("QWEN_IMAGE_REQUEST_WIDTH", 1280, "int"),
        "request_height": FieldDefinition("QWEN_IMAGE_REQUEST_HEIGHT", 720, "int"),
        "allowed_domains": FieldDefinition("QWEN_IMAGE_ALLOWED_DOMAINS", "dashscope.aliyuncs.com,aliyuncs.com,oss-cn-hangzhou.aliyuncs.com,oss-cn-beijing.aliyuncs.com,oss-cn-shanghai.aliyuncs.com,oss-cn-shenzhen.aliyuncs.com", "csv"),
        "endpoint_path": FieldDefinition("QWEN_IMAGE_ENDPOINT_PATH", "/api/v1/services/aigc/multimodal-generation/generation"),
        "workspace": FieldDefinition("QWEN_IMAGE_WORKSPACE", ""),
    }),
    "seedream": ProviderDefinition("seedream", "Seedream", "image_generation", {
        "enabled": FieldDefinition("SEEDREAM_ENABLED", True, "bool"),
        "api_key": FieldDefinition("SEEDREAM_API_KEY", "", "secret"),
        "base_url": FieldDefinition("SEEDREAM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "model": FieldDefinition("SEEDREAM_MODEL", ""),
        "timeout_seconds": FieldDefinition(("SEEDREAM_TIMEOUT_SECONDS", "IMAGE_GENERATION_TIMEOUT_SECONDS"), 60, "float"),
        "retry": FieldDefinition(("SEEDREAM_MAX_RETRIES", "IMAGE_GENERATION_MAX_RETRIES"), 0, "int"),
        "request_width": FieldDefinition("SEEDREAM_REQUEST_WIDTH", 1280, "int"),
        "request_height": FieldDefinition("SEEDREAM_REQUEST_HEIGHT", 720, "int"),
        "allowed_domains": FieldDefinition("SEEDREAM_ALLOWED_DOMAINS", "ark.cn-beijing.volces.com", "csv"),
        "endpoint_path": FieldDefinition("SEEDREAM_ENDPOINT_PATH", "/images/generations"),
        "workspace": FieldDefinition(None, ""),
    }),
}


def provider_definition(provider_id: str) -> ProviderDefinition:
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError("Unknown provider id.") from exc


def resolve_provider_values(
    provider_id: str,
    store: SecretStore | None = None,
    *,
    warnings: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve UI > Environment > Default without constructing a provider runtime."""
    definition = provider_definition(provider_id)
    secret_store = store or SecretStore()
    ui_config = secret_store.provider_config(provider_id)
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field_name, field_def in definition.fields.items():
        if field_name == "api_key":
            ui_key = secret_store.provider_api_key(provider_id)
            if ui_key:
                values[field_name] = ui_key
                sources[field_name] = "UI"
                continue
        if field_name in ui_config:
            value = _safe_candidate(
                provider_id,
                field_name,
                ui_config[field_name],
                field_def.kind,
                "UI",
                warnings,
            )
            if value is not _INVALID:
                values[field_name] = value
                sources[field_name] = "UI"
                continue
        if (env_value := first_env_value(field_def.env)) is not None:
            value = _safe_candidate(
                provider_id,
                field_name,
                env_value,
                field_def.kind,
                "Environment",
                warnings,
            )
            if value is not _INVALID:
                values[field_name] = value
                sources[field_name] = "Environment"
                continue
        values[field_name] = _validated_provider_value(
            provider_id,
            field_name,
            coerce_provider_value(field_def.default, field_def.kind, source="Default"),
        )
        sources[field_name] = "Default"
    for extra_name in ("allow_custom_base_url", "allow_local_endpoint"):
        if extra_name in ui_config:
            value = _safe_candidate(
                provider_id,
                extra_name,
                ui_config[extra_name],
                "bool",
                "UI",
                warnings,
            )
            if value is not _INVALID:
                values[extra_name] = value
                sources[extra_name] = "UI"
                continue
        values[extra_name] = False
        sources[extra_name] = "Default"
    if values.get("enabled") is False:
        values["api_key"] = ""
    return values, sources


def coerce_provider_value(value: Any, kind: str, *, source: str = "Environment") -> Any:
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if source == "UI":
            raise TypeError("UI bool values must be JSON booleans.")
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("Invalid boolean value.")
    if kind == "int":
        if source == "UI" and (isinstance(value, bool) or not isinstance(value, int)):
            raise TypeError("UI int values must be JSON integers.")
        return int(value)
    if kind == "float":
        if source == "UI" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise TypeError("UI float values must be JSON numbers.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Float values must be finite.")
        return result
    if kind == "csv":
        if isinstance(value, list):
            if any(not isinstance(item, str) for item in value):
                raise TypeError("CSV list items must be strings.")
            return [item.strip().lower() for item in value if item.strip()]
        if source == "UI":
            raise TypeError("UI CSV values must be JSON lists.")
        return [item.strip().lower() for item in str(value).split(",") if item.strip()]
    return str(value)


def _safe_candidate(
    provider_id: str,
    field_name: str,
    raw_value: Any,
    kind: str,
    source: str,
    warnings: list[str] | None,
) -> Any:
    try:
        value = coerce_provider_value(raw_value, kind, source=source)
        return _validated_provider_value(provider_id, field_name, value)
    except (TypeError, ValueError, OverflowError):
        message = (
            f"Ignored invalid {source} setting '{field_name}' for provider "
            f"'{provider_id}'; using the next configured source."
        )
        LOGGER.warning(message)
        if warnings is not None:
            warnings.append(message)
        return _INVALID


def _validated_provider_value(provider_id: str, field_name: str, value: Any) -> Any:
    ranges: dict[str, tuple[float, float]] = {
        "retry": (0, 5),
        "max_output_tokens": (128, 16000),
        "request_width": (64, 4096),
        "request_height": (64, 4096),
    }
    if field_name == "timeout_seconds":
        ranges[field_name] = (1, 600 if provider_id in {"qwen_image", "seedream"} else 300)
    if field_name in ranges:
        minimum, maximum = ranges[field_name]
        if isinstance(value, bool) or not minimum <= value <= maximum:
            raise ValueError("Provider setting is outside its supported range.")
    if field_name == "allowed_domains":
        if not isinstance(value, list) or not value or any(not _valid_hostname(item) for item in value):
            raise ValueError("Provider allowed domains are invalid.")
    return value


def _valid_hostname(value: str) -> bool:
    if not value or len(value) > 253 or "/" in value or ":" in value:
        return False
    labels = value.strip(".").split(".")
    return all(label and len(label) <= 63 and label.replace("-", "").isalnum() for label in labels)


def first_env_value(names: str | tuple[str, ...] | None) -> str | None:
    if names is None:
        return None
    for name in (names,) if isinstance(names, str) else names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return None
