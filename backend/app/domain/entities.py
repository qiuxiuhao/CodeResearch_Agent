from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, JsonValue


CodeEntityType = Literal[
    "repository",
    "directory",
    "file",
    "class",
    "function",
    "method",
    "model_module",
    "config",
    "training_entry",
    "inference_entry",
    "dataset",
]

PaperEntityType = Literal[
    "section",
    "paragraph",
    "formula",
    "figure",
    "table",
    "contribution",
    "method_module",
]


class CodeEntity(BaseModel):
    id: str
    repo_id: str
    entity_type: CodeEntityType
    path: str
    name: str
    qualified_name: str
    module_name: str | None = None
    parent_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None
    source_code: str | None = None
    docstring: str | None = None
    content_hash: str
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PaperEntity(BaseModel):
    id: str
    paper_id: str
    entity_type: PaperEntityType
    title: str | None = None
    text: str
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    figure_path: str | None = None
    keywords: list[str] = Field(default_factory=list)
    module_names: list[str] = Field(default_factory=list)
    content_hash: str
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
