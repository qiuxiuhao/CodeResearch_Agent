from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.schemas.teaching_diagram import TeachingDiagramManifest
from backend.app.teaching_diagrams.narrative import build_local_narrative
from backend.app.teaching_diagrams.skeleton_builder import build_teaching_diagram_skeletons
from backend.app.teaching_diagrams.spec_assembler import assemble_teaching_diagram_spec


def teaching_diagram_plan_node(state: AgentState) -> AgentState:
    if not state.get("teaching_diagrams_enabled", True):
        manifest = TeachingDiagramManifest(teaching_diagrams_enabled=False, status="disabled")
        return {**state, "teaching_diagram_manifest": manifest.model_dump(mode="json")}

    result = build_teaching_diagram_skeletons(
        repo_index=state.get("repo_index", {}),
        file_analysis=state.get("file_analysis", []),
        function_analysis=state.get("function_analysis", []),
        library_calls=state.get("library_calls", []),
        model_analysis=state.get("model_analysis", []),
        paper_analysis=state.get("paper_analysis", {}),
        paper_code_alignment=state.get("paper_code_alignment", {}),
        diagrams=state.get("diagrams", []),
        llm_explanations={
            "file": state.get("file_llm_explanations", []),
            "function": state.get("function_llm_explanations", []),
            "model": state.get("model_llm_explanations", []),
            "paper_code_alignment": state.get("paper_code_align_llm_explanations", []),
        },
        paper_figure_analysis=state.get("paper_figure_analysis", {}),
    )
    specs = []
    skeletons = []
    warnings = list(result.warnings)
    for skeleton in result.skeletons:
        narrative = build_local_narrative(skeleton)
        try:
            spec = assemble_teaching_diagram_spec(skeleton, narrative)
            skeletons.append(skeleton.model_dump(mode="json"))
            specs.append(spec.model_dump(mode="json"))
        except Exception as exc:
            warnings.append({
                "code": "teaching_diagram_spec_assembly_failed",
                "message": type(exc).__name__,
                "recoverable": True,
            })
    manifest = TeachingDiagramManifest(
        status="blueprint_only" if specs else "failed",
        teaching_diagrams_enabled=True,
        image_generation_enabled=state.get("image_generation_enabled", False),
        teaching_review_vlm_enabled=state.get("teaching_review_vlm_enabled", False),
        external_image_consent=state.get("external_image_consent", False),
        external_vision_consent=state.get("external_vision_consent", False),
        diagram_evidence_catalog=result.evidence_catalog,
        warnings=warnings,
        budget={
            "teaching_plan": state.get("teaching_plan_budget", {}),
            "teaching_image": state.get("teaching_image_budget", {}),
            "teaching_review": state.get("teaching_review_budget", {}),
        },
    )
    return {
        **state,
        "teaching_diagram_skeletons": skeletons,
        "teaching_diagram_specs": specs,
        "diagram_evidence_catalog": [item.model_dump(mode="json") for item in result.evidence_catalog],
        "teaching_diagram_warnings": warnings,
        "teaching_diagram_manifest": manifest.model_dump(mode="json"),
    }
