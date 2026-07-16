from __future__ import annotations

from backend.app.llm.budget import BudgetManager
from backend.app.llm.router import ModelRouter
from backend.app.llm.runtime import LLMRuntime
from backend.app.schemas.state import AgentState
from backend.app.schemas.teaching_diagram import TeachingDiagramManifest, TeachingDiagramNarrative, TeachingDiagramSkeleton
from backend.app.teaching_diagrams.narrative import build_local_narrative
from backend.app.teaching_diagrams.skeleton_builder import build_teaching_diagram_skeletons
from backend.app.teaching_diagrams.spec_assembler import assemble_teaching_diagram_spec


def teaching_diagram_plan_node(state: AgentState, llm_runtime: LLMRuntime | None = None) -> AgentState:
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
    plan_budget = BudgetManager(
        4,
        int(state.get("teaching_plan_budget", {}).get("max_provider_requests", 0)),
    )
    narrative_router = None
    if (
        state.get("text_llm_enabled", False)
        and state.get("external_text_consent", False)
        and llm_runtime is not None
    ):
        narrative_router = ModelRouter(llm_runtime.settings, llm_runtime.router.providers, plan_budget, llm_runtime.router.cache)
    for skeleton in result.skeletons:
        narrative = _build_narrative(skeleton, narrative_router, warnings) if narrative_router else build_local_narrative(skeleton)
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
            "teaching_plan": plan_budget.snapshot(),
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
        "teaching_plan_budget": plan_budget.snapshot(),
    }


def _build_narrative(
    skeleton: TeachingDiagramSkeleton,
    router: ModelRouter,
    warnings: list[dict | str],
) -> TeachingDiagramNarrative:
    local = build_local_narrative(skeleton)
    result = router.generate_structured(
        task_type="teaching_diagram_narrative",
        context_id=skeleton.skeleton_id,
        system_prompt=(
            "你是教学图文案规划器。只能生成通俗解释、分区标题、教学步骤、一句话总结、学习提示、"
            "布局和配色建议。不得新增、删除、重命名或修改 modules、connections、shapes、formulas、"
            "source entity、related Mermaid IDs。返回严格 JSON。"
        ),
        input_payload={
            "skeleton_id": skeleton.skeleton_id,
            "skeleton_hash": skeleton.skeleton_hash,
            "source_entity": skeleton.source_entity.model_dump(mode="json"),
            "sections": [item.model_dump(mode="json") for item in skeleton.sections],
            "modules": [item.model_dump(mode="json") for item in skeleton.modules],
            "connections": [item.model_dump(mode="json") for item in skeleton.connections],
            "shapes": [item.model_dump(mode="json") for item in skeleton.shapes],
            "formulas": [item.model_dump(mode="json") for item in skeleton.formulas],
            "related_mermaid_diagram_ids": skeleton.related_mermaid_diagram_ids,
            "allowed_output_fields": [
                "skeleton_id",
                "skeleton_hash",
                "section_titles",
                "plain_language_explanations",
                "teaching_steps",
                "one_sentence_summary",
                "learning_tips",
                "layout_suggestions",
                "color_suggestions",
                "warnings",
            ],
        },
        response_model=TeachingDiagramNarrative,
        evidence_catalog=[],
        prompt_version="1.3.2",
        identity_validator=lambda value: (
            isinstance(value, TeachingDiagramNarrative)
            and value.skeleton_id == skeleton.skeleton_id
            and value.skeleton_hash == skeleton.skeleton_hash
        ),
    )
    warnings.extend(result.warnings)
    if result.value is None:
        return local.model_copy(update={"warnings": [*local.warnings, "teaching_narrative_llm_unavailable_local_fallback"]})
    return TeachingDiagramNarrative.model_validate(result.value.model_dump(mode="json"))
