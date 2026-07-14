from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Confidence = Literal["high", "medium", "low"]
FigureType = Literal[
    "architecture", "pipeline", "workflow", "data_flow", "module_detail",
    "training_framework", "inference_framework", "comparison", "result_plot",
    "ablation", "qualitative_result", "dataset_example", "other",
]


class StrictVisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FigureCaption(StrictVisionModel):
    label: str = Field(min_length=1, max_length=80)
    normalized_label: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    bbox: tuple[float, float, float, float]
    confidence: Confidence = "medium"


class FigureAsset(StrictVisionModel):
    asset_id: str
    kind: Literal["xref", "inline", "render_fallback"]
    path: str
    mime_type: str
    byte_size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    xref: int | None = None
    bbox: tuple[float, float, float, float] | None = None


class FigurePreview(StrictVisionModel):
    path: str
    mime_type: str = "image/png"
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    render_dpi: int = Field(ge=36, le=600)
    source: Literal["figure_bbox_render", "original_asset_fallback"] = "figure_bbox_render"


class FigureSelection(StrictVisionModel):
    selected: bool = False
    score: float = 0
    reasons: list[str] = Field(default_factory=list, max_length=20)
    skip_reason: str | None = Field(default=None, max_length=200)


class PaperFigure(StrictVisionModel):
    figure_id: str = Field(pattern=r"^fig_[0-9a-f]{20}$")
    aliases: list[str] = Field(default_factory=list)
    page_number: int = Field(ge=1)
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)
    page_rotation: Literal[0, 90, 180, 270] = 0
    bbox: tuple[float, float, float, float]
    normalized_bbox: tuple[float, float, float, float]
    caption: FigureCaption
    original_assets: list[FigureAsset] = Field(default_factory=list)
    canonical_preview: FigurePreview | None = None
    reference_count: int = Field(default=0, ge=0)
    section_name: str | None = None
    selection: FigureSelection = Field(default_factory=FigureSelection)
    vlm_analysis: dict | None = None


class VisionEvidenceItem(StrictVisionModel):
    evidence_id: str = Field(min_length=1, max_length=300)
    evidence_type: Literal["figure", "caption", "paper_contribution", "paper_reference"]
    fact_summary: str = Field(min_length=1, max_length=2000)
    figure_id: str | None = None
    contribution_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    confidence: Confidence = "medium"


class FigureModule(StrictVisionModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=600)


class FigureFlow(StrictVisionModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=500)


class VisualRelation(StrictVisionModel):
    subject: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=300)
    object: str = Field(min_length=1, max_length=200)


class FigureContributionCandidate(StrictVisionModel):
    contribution_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    confidence: Confidence = "low"


class VisionCallMetadata(StrictVisionModel):
    status: Literal["success", "fallback", "failed", "skipped"]
    provider: str | None = None
    model: str | None = None
    attempts: int = Field(default=0, ge=0)
    fallback_used: bool = False
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    image_hash: str = Field(min_length=64, max_length=64)
    generated_at: datetime
    cache_hit: bool = False
    prompt_version: str
    warning_codes: list[str] = Field(default_factory=list)


class FigureAnalysis(StrictVisionModel):
    figure_id: str = Field(pattern=r"^fig_[0-9a-f]{20}$")
    figure_type: FigureType
    summary: str = Field(min_length=1, max_length=2000)
    modules: list[FigureModule] = Field(default_factory=list, max_length=30)
    flows: list[FigureFlow] = Field(default_factory=list, max_length=40)
    inputs: list[str] = Field(default_factory=list, max_length=20)
    outputs: list[str] = Field(default_factory=list, max_length=20)
    visual_relations: list[VisualRelation] = Field(default_factory=list, max_length=40)
    contribution_candidates: list[FigureContributionCandidate] = Field(default_factory=list, max_length=10)
    uncertainties: list[str] = Field(default_factory=list, max_length=15)
    evidence_refs: list[str] = Field(default_factory=list, max_length=40)
    metadata: VisionCallMetadata | None = None

    @model_validator(mode="after")
    def reject_uncontrolled_markup(self):
        values = self.model_dump(exclude={"metadata"})
        stack: list[object] = [values]
        while stack:
            value = stack.pop()
            if isinstance(value, str) and ("```" in value or "<script" in value.lower()):
                raise ValueError("Figure analysis must not contain code fences or HTML scripts.")
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
        return self


class SuggestedCodeLink(StrictVisionModel):
    figure_id: str
    contribution_id: str
    code_evidence_refs: list[str] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=1500)
    confidence: Confidence = "low"
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    suggested: Literal[True] = True
