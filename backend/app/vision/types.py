from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


class VisionProviderCapabilities(BaseModel):
    supports_json_schema: bool = False
    supports_json_object: bool = False
    supports_tool_calling: bool = False


@dataclass(slots=True)
class VisionRequest:
    context_id: str
    system_prompt: str
    input_payload: dict[str, Any]
    image_bytes: bytes
    mime_type: str
    response_model: type[BaseModel]
    max_output_tokens: int


@dataclass(slots=True)
class VisionResponse:
    data: dict[str, Any]
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class VisionRouterResult:
    value: BaseModel | None
    warnings: list[dict] = field(default_factory=list)
