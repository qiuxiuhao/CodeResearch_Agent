from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Confidence = Literal["high", "medium", "low"]
AlignmentStatus = Literal["matched", "unmatched"]


class PaperKeyword(BaseModel):
    text: str
    source: Literal["title", "abstract", "method", "contribution", "frequency"]
    evidence: list[str] = Field(default_factory=list)


class PaperSection(BaseModel):
    name: str
    title: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    evidence: list[str] = Field(default_factory=list)


class PaperContribution(BaseModel):
    id: str
    title: str
    description: str
    source_section: str | None = None
    page_no: int | None = None
    keywords: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class PaperAnalysis(BaseModel):
    paper_provided: bool = False
    paper_path: str | None = None
    title: str | None = None
    abstract: str | None = None
    method_text: str | None = None
    sections: list[PaperSection] = Field(default_factory=list)
    contributions: list[PaperContribution] = Field(default_factory=list)
    keywords: list[PaperKeyword] = Field(default_factory=list)
    module_names: list[str] = Field(default_factory=list)
    raw_text_char_count: int = 0
    page_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    confidence: Confidence = "medium"


class PaperCodeTarget(BaseModel):
    target_type: Literal["file", "class", "function", "model_module"]
    name: str
    file_path: str | None = None
    qualified_name: str | None = None
    line_no: int | None = None
    evidence: list[str] = Field(default_factory=list)


class PaperCodeAlignmentItem(BaseModel):
    contribution_id: str
    contribution_title: str
    status: AlignmentStatus = "unmatched"
    matched_targets: list[PaperCodeTarget] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    reason: str
    confidence: Confidence = "low"
    evidence: list[str] = Field(default_factory=list)


class UnmatchedContribution(BaseModel):
    contribution_id: str
    contribution_title: str
    reason: str


class PaperCodeAlignment(BaseModel):
    paper_provided: bool = False
    alignment_items: list[PaperCodeAlignmentItem] = Field(default_factory=list)
    unmatched_contributions: list[UnmatchedContribution] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
