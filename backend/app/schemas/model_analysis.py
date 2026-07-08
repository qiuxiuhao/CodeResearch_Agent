from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Confidence = Literal["high", "medium", "low"]

ComponentRole = Literal[
    "encoder",
    "decoder",
    "backbone",
    "head",
    "loss",
    "classifier",
    "embedding",
    "normalization",
    "activation",
    "unknown",
]


class ModelLayer(BaseModel):
    name: str
    assigned_name: str
    layer_type: str
    call_text: str
    line_no: int | None = None
    role: ComponentRole = "unknown"
    source: Literal["init_assignment", "forward_call", "library_call"] = "init_assignment"
    evidence: list[str] = Field(default_factory=list)


class ForwardStep(BaseModel):
    order: int
    target: str | None = None
    expression: str
    calls: list[str] = Field(default_factory=list)
    uses_layers: list[str] = Field(default_factory=list)
    line_no: int | None = None
    explanation: str
    evidence: list[str] = Field(default_factory=list)


class ModelComponentCandidate(BaseModel):
    name: str
    role: ComponentRole
    file_path: str
    class_name: str
    line_no: int | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class ModelAnalysis(BaseModel):
    file_path: str
    class_name: str
    qualified_name: str
    base_classes: list[str] = Field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None

    is_nn_module: bool = False
    is_main_model_candidate: bool = False
    main_model_reason: str | None = None

    init_function: str | None = None
    forward_function: str | None = None
    model_inputs: list[str] = Field(default_factory=list)
    model_outputs: list[str] = Field(default_factory=list)

    layers: list[ModelLayer] = Field(default_factory=list)
    forward_steps: list[ForwardStep] = Field(default_factory=list)
    component_candidates: list[ModelComponentCandidate] = Field(default_factory=list)

    summary: str
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
