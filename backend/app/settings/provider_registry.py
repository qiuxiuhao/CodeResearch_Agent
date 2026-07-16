from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.app.settings.secret_store import SecretStore


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
        "supports_async": FieldDefinition("QWEN_IMAGE_SUPPORTS_ASYNC", False, "bool"),
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
        "supports_async": FieldDefinition("SEEDREAM_SUPPORTS_ASYNC", False, "bool"),
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
            values[field_name] = coerce_provider_value(ui_config[field_name], field_def.kind)
            sources[field_name] = "UI"
        elif (env_value := first_env_value(field_def.env)) is not None:
            values[field_name] = coerce_provider_value(env_value, field_def.kind)
            sources[field_name] = "Environment"
        else:
            values[field_name] = coerce_provider_value(field_def.default, field_def.kind)
            sources[field_name] = "Default"
    for extra_name in ("allow_custom_base_url", "allow_local_endpoint"):
        if extra_name in ui_config:
            values[extra_name] = coerce_provider_value(ui_config[extra_name], "bool")
            sources[extra_name] = "UI"
        else:
            values[extra_name] = False
            sources[extra_name] = "Default"
    if values.get("enabled") is False:
        values["api_key"] = ""
    return values, sources


def coerce_provider_value(value: Any, kind: str) -> Any:
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


def first_env_value(names: str | tuple[str, ...] | None) -> str | None:
    if names is None:
        return None
    for name in (names,) if isinstance(names, str) else names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return None
