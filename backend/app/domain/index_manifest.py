from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class SymbolChunk(BaseModel):
    id: str
    repo_id: str
    entity_id: str
    entity_kind: Literal["code", "paper"]
    chunk_type: Literal["function", "method", "class", "file", "model_module", "paper_entity"]
    path: str | None = None
    page_number: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    ordinal: int = 0
    text: str
    content_hash: str
    char_count: int = Field(ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class IndexedFile(BaseModel):
    path: str
    kind: Literal["python", "config", "other"]
    content_hash: str
    size_bytes: int = Field(ge=0)
    parse_status: Literal["success", "partial", "failed", "skipped"]
    entity_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    errors: list[dict[str, JsonValue]] = Field(default_factory=list)


class IndexManifest(BaseModel):
    manifest_version: str
    index_schema_version: str
    repo_id: str
    repository_identity_mode: Literal["explicit", "task_scoped"]
    index_version_id: str
    index_sequence: int = Field(ge=1)
    input_hash: str
    status: Literal["active", "failed", "in_progress", "reused"]
    builder_versions: dict[str, str]
    file_count: int = Field(ge=0)
    code_entity_count: int = Field(ge=0)
    paper_entity_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    unresolved_call_count: int = Field(ge=0)
    ambiguous_call_count: int = Field(ge=0)
    created_at: datetime
    activated_at: datetime | None = None
    warnings: list[dict[str, JsonValue]] = Field(default_factory=list)
