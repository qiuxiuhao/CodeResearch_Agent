from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.library_call import LibraryCall


Confidence = Literal["high", "medium", "low"]


class FunctionAnalysis(BaseModel):
    file_path: str
    class_name: str | None = None
    function_name: str
    qualified_name: str
    start_line: int | None = None
    end_line: int | None = None

    purpose: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    implementation_logic: list[str] = Field(default_factory=list)
    computation_logic: list[str] = Field(default_factory=list)
    model_position: str | None = None

    called_internal_functions: list[str] = Field(default_factory=list)
    library_calls: list[LibraryCall] = Field(default_factory=list)

    is_core_function: bool = False
    core_reason: str | None = None
    beginner_explanation: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"

