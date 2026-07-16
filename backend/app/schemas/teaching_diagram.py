from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "1.3.2"
Confidence = Literal["high", "medium", "low"]


class StrictTeachingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeachingDiagramEvidenceItem(StrictTeachingModel):
    evidence_id: str = Field(min_length=1, max_length=240)
    evidence_type: Literal[
        "repo_index",
        "file_analysis",
        "function_analysis",
        "library_call",
        "model_analysis",
        "paper_analysis",
        "paper_code_alignment",
        "diagram",
    ]
    fact_summary: str = Field(min_length=1, max_length=1000)
    file_path: str | None = None
    class_name: str | None = None
    function_name: str | None = None
    qualified_name: str | None = None
    line_no: int | None = Field(default=None, ge=1)
    diagram_id: str | None = None
    confidence: Confidence = "medium"


class TeachingDiagramSourceEntity(StrictTeachingModel):
    entity_type: Literal["model", "function", "data_flow", "paper_alignment"]
    entity_id: str
    title: str
    file_path: str | None = None
    qualified_name: str | None = None
    class_name: str | None = None


class TeachingDiagramSection(StrictTeachingModel):
    id: str
    title: str
    module_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class TeachingDiagramModule(StrictTeachingModel):
    id: str
    label: str
    kind: Literal["input", "output", "layer", "operation", "function", "module", "loss", "unknown"] = "module"
    section_id: str | None = None
    role: str | None = None
    evidence_refs: list[str] = Field(min_length=1)


class TeachingDiagramConnection(StrictTeachingModel):
    id: str
    source_module_id: str
    target_module_id: str
    label: str | None = None
    direction: Literal["left_to_right", "top_to_bottom"] = "left_to_right"
    evidence_refs: list[str] = Field(min_length=1)


class TeachingDiagramShape(StrictTeachingModel):
    module_id: str
    label: str
    evidence_refs: list[str] = Field(min_length=1)


class TeachingDiagramFormula(StrictTeachingModel):
    id: str
    text: str
    evidence_refs: list[str] = Field(min_length=1)


class TeachingDiagramLegendItem(StrictTeachingModel):
    label: str
    color: str
    meaning: str


class TeachingDiagramSkeleton(StrictTeachingModel):
    skeleton_id: str
    source_entity: TeachingDiagramSourceEntity
    related_mermaid_diagram_ids: list[str] = Field(default_factory=list)
    sections: list[TeachingDiagramSection] = Field(default_factory=list)
    modules: list[TeachingDiagramModule] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    connections: list[TeachingDiagramConnection] = Field(default_factory=list)
    shapes: list[TeachingDiagramShape] = Field(default_factory=list)
    formulas: list[TeachingDiagramFormula] = Field(default_factory=list)
    legend_items: list[TeachingDiagramLegendItem] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    skeleton_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_structure_refs(self):
        module_ids = {item.id for item in self.modules}
        for connection in self.connections:
            if connection.source_module_id not in module_ids or connection.target_module_id not in module_ids:
                raise ValueError("Teaching diagram connection references an unknown module.")
        for shape in self.shapes:
            if shape.module_id not in module_ids:
                raise ValueError("Teaching diagram shape references an unknown module.")
        return self


class TeachingDiagramNarrative(StrictTeachingModel):
    skeleton_id: str
    skeleton_hash: str = Field(min_length=64, max_length=64)
    section_titles: dict[str, str] = Field(default_factory=dict)
    plain_language_explanations: dict[str, str] = Field(default_factory=dict)
    teaching_steps: list[str] = Field(default_factory=list)
    one_sentence_summary: str
    learning_tips: list[str] = Field(default_factory=list)
    layout_suggestions: list[str] = Field(default_factory=list)
    color_suggestions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: Any = Field(default_factory=dict)


class TeachingDiagramStyleHints(StrictTeachingModel):
    direction: Literal["left_to_right", "top_to_bottom"] = "left_to_right"
    palette: list[str] = Field(default_factory=lambda: ["#2563eb", "#059669", "#f59e0b", "#7c3aed"])
    layout: str = "deterministic_blueprint"


class TeachingDiagramSpec(StrictTeachingModel):
    schema_version: Literal["1.3.2"] = SCHEMA_VERSION
    diagram_id: str
    related_mermaid_diagram_ids: list[str] = Field(default_factory=list)
    source_entity: TeachingDiagramSourceEntity
    skeleton_hash: str = Field(min_length=64, max_length=64)
    public_spec_hash: str = Field(min_length=64, max_length=64)
    sections: list[TeachingDiagramSection] = Field(default_factory=list)
    modules: list[TeachingDiagramModule] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    connections: list[TeachingDiagramConnection] = Field(default_factory=list)
    shapes: list[TeachingDiagramShape] = Field(default_factory=list)
    formulas: list[TeachingDiagramFormula] = Field(default_factory=list)
    legend: list[TeachingDiagramLegendItem] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    one_sentence_summary: str
    learning_tips: list[str] = Field(default_factory=list)
    style_hints: TeachingDiagramStyleHints = Field(default_factory=TeachingDiagramStyleHints)
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("one_sentence_summary")
    @classmethod
    def reject_markup(cls, value: str) -> str:
        lowered = value.lower()
        if "```" in value or "<script" in lowered or "<svg" in lowered:
            raise ValueError("Teaching diagram text must not contain code fences, scripts, or SVG markup.")
        return value


class TeachingDiagramAsset(StrictTeachingModel):
    path: str
    mime_type: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)


class TeachingDiagramProviderAttempt(StrictTeachingModel):
    provider: str
    model: str | None = None
    status: Literal["success", "failed", "skipped", "cache_hit"]
    warning_code: str | None = None


class TeachingDiagramReview(StrictTeachingModel):
    diagram_id: str
    passed: bool
    overall_score: int = Field(ge=0, le=100)
    accuracy_score: int = Field(ge=1, le=5)
    spec_coverage_score: int = Field(ge=1, le=5)
    label_readability_score: int = Field(ge=1, le=5)
    beginner_clarity_score: int = Field(ge=1, le=5)
    safety_score: int = Field(ge=1, le=5)
    missing_required_items: list[str] = Field(default_factory=list)
    hallucinated_items: list[str] = Field(default_factory=list)
    incorrect_shapes: list[str] = Field(default_factory=list)
    incorrect_formulas: list[str] = Field(default_factory=list)
    unreadable_labels: list[str] = Field(default_factory=list)
    simplification_notes: list[str] = Field(default_factory=list)
    recommendation: Literal["pass", "fallback_blueprint"] = "fallback_blueprint"
    metadata: dict = Field(default_factory=dict)


class TeachingDiagramManifestItem(StrictTeachingModel):
    diagram_id: str
    title: str
    related_mermaid_diagram_ids: list[str] = Field(default_factory=list)
    source_entity: TeachingDiagramSourceEntity
    spec_path: str
    blueprint_svg: TeachingDiagramAsset | None = None
    blueprint_png: TeachingDiagramAsset | None = None
    generated_raw: TeachingDiagramAsset | None = None
    styled_composite: TeachingDiagramAsset | None = None
    final_asset: TeachingDiagramAsset | None = None
    review: TeachingDiagramReview | None = None
    display_variant: Literal["blueprint", "ai"] = "blueprint"
    display_asset: TeachingDiagramAsset | None = None
    fallback_reason: str | None = None
    provider_attempts: list[TeachingDiagramProviderAttempt] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TeachingDiagramManifest(StrictTeachingModel):
    version: Literal["1.3.2"] = SCHEMA_VERSION
    status: Literal["success", "partial", "blueprint_only", "disabled", "failed"] = "disabled"
    teaching_diagrams_enabled: bool = True
    image_generation_enabled: bool = False
    teaching_review_vlm_enabled: bool = False
    external_image_consent: bool = False
    external_vision_consent: bool = False
    budget: dict = Field(default_factory=dict)
    diagram_evidence_catalog: list[TeachingDiagramEvidenceItem] = Field(default_factory=list)
    diagrams: list[TeachingDiagramManifestItem] = Field(default_factory=list)
    warnings: list[dict | str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    generated_at: datetime | None = None
