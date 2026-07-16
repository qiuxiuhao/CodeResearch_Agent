from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


FieldSource = Literal["UI", "Environment", "Default"]
ProviderGroup = Literal["text_llm", "vision_vlm", "image_generation"]
ApiKeySource = Literal["UI", "Environment", "None"]


class ProviderPublicSettings(BaseModel):
    id: str
    display_name: str
    group: ProviderGroup
    enabled: bool = True
    configured: bool = False
    masked_key: str | None = None
    api_key_source: ApiKeySource = "None"
    revision: int = 0
    source: dict[str, FieldSource] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ProviderSettingsListResponse(BaseModel):
    revision: int
    providers: list[ProviderPublicSettings]
    warnings: list[str] = Field(default_factory=list)


class ProviderSettingsUpdateRequest(BaseModel):
    expected_revision: int
    enabled: bool | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout_seconds: float | None = None
    retry: int | None = None
    max_output_tokens: int | None = None
    request_width: int | None = None
    request_height: int | None = None
    allowed_domains: list[str] | None = None
    endpoint_path: str | None = None
    workspace: str | None = None
    supports_async: bool | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated compatibility field. false is ignored; true is rejected. Removed in v1.4.",
    )
    supports_json_object: bool | None = None
    disable_thinking: bool | None = None
    allow_custom_base_url: bool | None = None
    allow_local_endpoint: bool | None = None


class ProviderApiKeyDeleteRequest(BaseModel):
    expected_revision: int


class ProviderValidateRequest(BaseModel):
    enabled: bool | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout_seconds: float | None = None
    retry: int | None = None
    max_output_tokens: int | None = None
    request_width: int | None = None
    request_height: int | None = None
    allowed_domains: list[str] | None = None
    endpoint_path: str | None = None
    supports_async: bool | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated compatibility field. false is ignored; true is rejected. Removed in v1.4.",
    )
    supports_json_object: bool | None = None
    disable_thinking: bool | None = None
    allow_custom_base_url: bool = False
    allow_local_endpoint: bool = False


class ProviderValidateResponse(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProviderTestRequest(BaseModel):
    confirm_cost: bool = False


class ProviderTestResponse(BaseModel):
    success: bool
    provider: str
    model: str | None = None
    latency_ms: int | None = None
    warning: str | None = None
