from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SourceType = Literal["template_generated", "manual", "official_doc", "llm_generated"]
Confidence = Literal["high", "medium", "low"]


class LibraryFunctionDoc(BaseModel):
    id: int | None = None
    canonical_name: str
    display_name: str
    package_name: str | None = None
    category: str | None = None

    source_type: SourceType = "template_generated"
    summary: str
    beginner_explanation: str
    parameters_explanation: list[str] = Field(default_factory=list)
    return_explanation: str | None = None
    common_usage: str | None = None
    code_example: str | None = None
    shape_or_tensor_note: str | None = None
    common_mistakes: list[str] = Field(default_factory=list)
    related_functions: list[str] = Field(default_factory=list)
    official_doc_url: str | None = None
    confidence: Confidence = "medium"
    created_at: str | None = None
    updated_at: str | None = None


class LibraryFunctionProcessResult(BaseModel):
    library_function_docs: list[LibraryFunctionDoc] = Field(default_factory=list)
    new_library_functions: list[LibraryFunctionDoc] = Field(default_factory=list)
    updated_library_calls: list[dict] = Field(default_factory=list)
    skipped_low_confidence_calls: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
