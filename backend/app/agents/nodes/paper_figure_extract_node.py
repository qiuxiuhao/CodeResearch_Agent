from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.paper_figure_extract_tool import empty_figure_analysis, extract_paper_figures
from backend.app.vision.runtime import VisionRuntime


def paper_figure_extract_node(state: AgentState, vision_runtime: VisionRuntime | None = None) -> AgentState:
    enabled = bool(state.get("vision_vlm_enabled", False))
    consent = bool(state.get("external_vision_consent", False))
    if not state.get("paper_pdf_path") or not state.get("paper_analysis", {}).get("paper_provided"):
        return {**state, "paper_figure_analysis": empty_figure_analysis(vision_enabled=enabled, consent=consent)}
    if vision_runtime is None:
        return {**state, "paper_figure_analysis": empty_figure_analysis(vision_enabled=enabled, consent=consent, status="skipped")}
    result = extract_paper_figures(
        state["paper_pdf_path"], state["output_dir"], state.get("paper_analysis", {}),
        vision_runtime.settings, external_vision_consent=consent,
    )
    return {**state, "paper_figure_analysis": result}
