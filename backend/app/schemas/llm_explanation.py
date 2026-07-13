from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Confidence = Literal["high", "medium", "low"]
CallStatus = Literal["success", "fallback", "skipped", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=300)
    evidence_type: str = Field(min_length=1, max_length=60)
    file_path: str | None = Field(default=None, max_length=500)
    class_name: str | None = Field(default=None, max_length=200)
    function_name: str | None = Field(default=None, max_length=200)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    rule_field: str | None = Field(default=None, max_length=200)
    fact_summary: str = Field(min_length=1, max_length=2000)
    confidence: Confidence = "medium"


class LLMCallMetadata(StrictModel):
    task_type: str
    status: CallStatus
    provider: str | None = None
    model: str | None = None
    attempts: int = Field(default=0, ge=0)
    fallback_used: bool = False
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    input_truncated: bool = False
    input_hash: str = Field(min_length=64, max_length=64)
    generated_at: datetime
    cache_hit: bool = False
    prompt_version: str = Field(min_length=1, max_length=40)
    warning_codes: list[str] = Field(default_factory=list, max_length=20)


class ExplanationBase(StrictModel):
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    metadata: LLMCallMetadata | None = None

    @model_validator(mode="after")
    def reject_uncontrolled_markup(self):
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)

        payload = self.model_dump(exclude={"metadata"})
        if any("```" in text or re.search(r"<[A-Za-z][^>]*>", text) for text in strings(payload)):
            raise ValueError("LLM explanation must not contain Markdown code fences or HTML tags.")
        return self


class FunctionLLMExplanation(ExplanationBase):
    file_path: str = Field(max_length=500)
    qualified_name: str = Field(max_length=300)
    summary: str = Field(min_length=1, max_length=1500)
    logic_summary: list[str] = Field(default_factory=list, max_length=12)
    teaching_explanation: str = Field(min_length=1, max_length=3000)
    key_points: list[str] = Field(default_factory=list, max_length=12)
    input_output_notes: list[str] = Field(default_factory=list, max_length=12)


class FileLLMExplanation(ExplanationBase):
    file_path: str = Field(max_length=500)
    summary: str = Field(min_length=1, max_length=1500)
    architecture_role: str = Field(min_length=1, max_length=2000)
    reading_guide: list[str] = Field(default_factory=list, max_length=12)
    key_relationships: list[str] = Field(default_factory=list, max_length=12)


class ModelLLMExplanation(ExplanationBase):
    file_path: str = Field(max_length=500)
    class_name: str = Field(max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    data_flow_explanation: list[str] = Field(default_factory=list, max_length=20)
    module_explanations: list[str] = Field(default_factory=list, max_length=20)
    learning_notes: list[str] = Field(default_factory=list, max_length=12)


class PaperCodeAlignLLMExplanation(ExplanationBase):
    contribution_id: str = Field(max_length=200)
    contribution_title: str = Field(max_length=500)
    alignment_summary: str = Field(min_length=1, max_length=2500)
    evidence_interpretation: list[str] = Field(default_factory=list, max_length=20)
    teaching_explanation: str = Field(min_length=1, max_length=3000)
    needs_review: bool = False
