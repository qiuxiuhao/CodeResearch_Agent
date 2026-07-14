from __future__ import annotations

import hashlib
import json

from backend.app.schemas.teaching_diagram import (
    SCHEMA_VERSION,
    TeachingDiagramNarrative,
    TeachingDiagramSkeleton,
    TeachingDiagramSpec,
    TeachingDiagramStyleHints,
)


def assemble_teaching_diagram_spec(
    skeleton: TeachingDiagramSkeleton,
    narrative: TeachingDiagramNarrative,
) -> TeachingDiagramSpec:
    warnings = list(skeleton.warnings)
    if narrative.skeleton_id != skeleton.skeleton_id or narrative.skeleton_hash != skeleton.skeleton_hash:
        warnings.append("LLM Narrative 与 Skeleton 身份不匹配，已使用本地模板文案。")
        from backend.app.teaching_diagrams.narrative import build_local_narrative

        narrative = build_local_narrative(skeleton)
    sections = [
        section.model_copy(update={"title": narrative.section_titles.get(section.id, section.title)})
        for section in skeleton.sections
    ]
    public_without_hash = {
        "schema_version": SCHEMA_VERSION,
        "diagram_id": _diagram_id(skeleton),
        "related_mermaid_diagram_ids": skeleton.related_mermaid_diagram_ids,
        "source_entity": skeleton.source_entity.model_dump(),
        "skeleton_hash": skeleton.skeleton_hash,
        "sections": [item.model_dump() for item in sections],
        "modules": [item.model_dump() for item in skeleton.modules],
        "inputs": skeleton.inputs,
        "outputs": skeleton.outputs,
        "connections": [item.model_dump() for item in skeleton.connections],
        "shapes": [item.model_dump() for item in skeleton.shapes],
        "formulas": [item.model_dump() for item in skeleton.formulas],
        "legend": [item.model_dump() for item in skeleton.legend_items],
        "steps": narrative.teaching_steps,
        "one_sentence_summary": narrative.one_sentence_summary,
        "learning_tips": narrative.learning_tips,
        "style_hints": TeachingDiagramStyleHints().model_dump(),
        "evidence_refs": sorted(set([
            *skeleton.evidence_refs,
            *(ref for module in skeleton.modules for ref in module.evidence_refs),
            *(ref for edge in skeleton.connections for ref in edge.evidence_refs),
            *(ref for shape in skeleton.shapes for ref in shape.evidence_refs),
            *(ref for formula in skeleton.formulas for ref in formula.evidence_refs),
        ])),
        "warnings": warnings,
    }
    public_spec_hash = _hash(public_without_hash)
    return TeachingDiagramSpec(**public_without_hash, public_spec_hash=public_spec_hash)


def public_spec_for_provider(spec: TeachingDiagramSpec) -> dict:
    payload = spec.model_dump(mode="json")
    payload.pop("warnings", None)
    return payload


def _diagram_id(skeleton: TeachingDiagramSkeleton) -> str:
    return f"td_{_hash({'source_entity': skeleton.source_entity.model_dump(), 'skeleton_hash': skeleton.skeleton_hash, 'schema_version': SCHEMA_VERSION})[:20]}"


def _hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
