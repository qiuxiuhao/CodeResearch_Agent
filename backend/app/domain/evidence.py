from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EvidenceRef(BaseModel):
    id: str
    source_type: Literal["code", "paper", "figure", "alignment"]
    entity_id: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    paper_id: str | None = None
    page_number: int | None = None
    figure_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    content_hash: str | None = None
