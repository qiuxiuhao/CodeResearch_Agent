from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ImageProviderCapabilities(BaseModel):
    supported_mime_types: list[str] = Field(default_factory=lambda: ["image/png"])
    supported_sizes: list[tuple[int, int]] = Field(default_factory=list)
    supports_seed: bool = False
    supports_negative_prompt: bool = False
    supports_quality: bool = False
    supports_style_reference: bool = False
    supports_json_prompt: bool = False
    max_prompt_chars: int = 6000
    max_output_pixels: int = 1536 * 1536


@dataclass(slots=True)
class ImageGenerationRequest:
    diagram_id: str
    public_spec: dict[str, Any]
    prompt_version: str
    schema_version: str
    width: int
    height: int
    mime_type: str
    max_output_bytes: int
    output_dir: Path


@dataclass(slots=True)
class ImageGenerationResponse:
    image_bytes: bytes | None = None
    mime_type: str = "image/png"
    latency_ms: int = 0
    remote_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageRouterResult:
    image_path: Path | None
    mime_type: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
