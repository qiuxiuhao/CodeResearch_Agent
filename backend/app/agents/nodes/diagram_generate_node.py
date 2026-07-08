from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.mermaid_tool import generate_diagrams


def diagram_generate_node(state: AgentState) -> AgentState:
    result = generate_diagrams(
        repo_index=state.get("repo_index", {}),
        file_analysis=state.get("file_analysis", []),
        function_analysis=state.get("function_analysis", []),
        model_analysis=state.get("model_analysis", []),
        paper_analysis=state.get("paper_analysis", {}),
        paper_code_alignment=state.get("paper_code_alignment", {}),
        library_calls=state.get("library_calls", []),
    )
    return {
        **state,
        "diagrams": [diagram.model_dump() for diagram in result.diagrams],
        "diagram_warnings": result.warnings,
        "errors": [*state.get("errors", []), *result.errors],
    }
