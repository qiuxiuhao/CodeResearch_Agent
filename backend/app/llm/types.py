from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


LLMTaskType = Literal[
    "function_explain",
    "file_explain",
    "model_explain",
    "paper_code_align",
    "teaching_diagram_narrative",
    "research_answer",
    "research_plan",
]


class ProviderCapabilities(BaseModel):
    supports_json_schema: bool = False
    supports_json_object: bool = False
    supports_tool_calling: bool = False


@dataclass(slots=True)
class ProviderRequest:
    task_type: LLMTaskType
    system_prompt: str
    input_payload: dict[str, Any]
    response_model: type[BaseModel]
    max_output_tokens: int


@dataclass(slots=True)
class ProviderResponse:
    data: dict[str, Any]
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class RouterResult:
    value: BaseModel | None
    warnings: list[dict] = field(default_factory=list)
