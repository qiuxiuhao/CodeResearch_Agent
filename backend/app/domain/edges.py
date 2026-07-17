from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, JsonValue, model_validator


EdgeType = Literal[
    "CONTAINS",
    "DEFINES",
    "IMPORTS",
    "CALLS",
    "INHERITS",
    "INSTANTIATES",
    "CONFIGURES",
    "TRAINS",
    "USED_IN_INFERENCE",
    "NEXT_MODULE",
    "ALIGNS_WITH",
]

ResolutionType = Literal[
    "exact",
    "alias",
    "relative",
    "self_method",
    "model_forward",
    "duplicate_last_definition",
    "ambiguous",
    "unresolved",
]


class KnowledgeEdge(BaseModel):
    id: str
    repo_id: str
    source_id: str
    target_id: str | None = None
    edge_type: EdgeType
    confidence: float = Field(ge=0.0, le=1.0)
    resolution_type: ResolutionType
    unresolved_symbol: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_resolution(self) -> "KnowledgeEdge":
        if self.target_id is None:
            if self.resolution_type not in {"ambiguous", "unresolved"}:
                raise ValueError("A target-less edge must be ambiguous or unresolved.")
            if not self.unresolved_symbol:
                raise ValueError("A target-less edge must retain unresolved_symbol.")
        return self
