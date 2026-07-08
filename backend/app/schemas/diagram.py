from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Confidence = Literal["high", "medium", "low"]

DiagramType = Literal[
    "project_structure",
    "model_flow",
    "core_modules",
    "function_logic",
    "paper_code_alignment",
]

NodeType = Literal[
    "file",
    "class",
    "function",
    "model",
    "layer",
    "component",
    "paper_contribution",
    "paper_keyword",
    "unknown",
]


class DiagramSourceRef(BaseModel):
    source_type: Literal[
        "repo_index",
        "file_analysis",
        "function_analysis",
        "model_analysis",
        "paper_analysis",
        "paper_code_alignment",
    ]
    file_path: str | None = None
    qualified_name: str | None = None
    class_name: str | None = None
    function_name: str | None = None
    line_no: int | None = None
    contribution_id: str | None = None
    evidence: list[str] = Field(default_factory=list)


class DiagramNode(BaseModel):
    id: str
    label: str
    node_type: NodeType
    source_refs: list[DiagramSourceRef] = Field(default_factory=list)
    confidence: Confidence = "medium"
    is_uncertain: bool = False


class DiagramEdge(BaseModel):
    source: str
    target: str
    label: str | None = None
    source_refs: list[DiagramSourceRef] = Field(default_factory=list)
    confidence: Confidence = "medium"
    is_uncertain: bool = False


class Diagram(BaseModel):
    id: str
    title: str
    diagram_type: DiagramType
    description: str
    mermaid: str
    nodes: list[DiagramNode] = Field(default_factory=list)
    edges: list[DiagramEdge] = Field(default_factory=list)
    source_refs: list[DiagramSourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class DiagramGenerationResult(BaseModel):
    diagrams: list[Diagram] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
