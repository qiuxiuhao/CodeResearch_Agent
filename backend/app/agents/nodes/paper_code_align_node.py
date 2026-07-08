from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.paper_code_align_tool import align_paper_to_code, empty_paper_code_alignment


def paper_code_align_node(state: AgentState) -> AgentState:
    paper_analysis = state.get("paper_analysis", {})
    if not paper_analysis.get("paper_provided"):
        return {
            **state,
            "paper_code_alignment": empty_paper_code_alignment("未提供论文 PDF，跳过论文代码对齐。").model_dump(),
        }

    alignment = align_paper_to_code(
        paper_analysis=paper_analysis,
        repo_index=state.get("repo_index", {}),
        file_analysis=state.get("file_analysis", []),
        classes=state.get("classes", []),
        functions=state.get("functions", []),
        function_analysis=state.get("function_analysis", []),
        model_analysis=state.get("model_analysis", []),
        library_calls=state.get("library_calls", []),
    )
    return {
        **state,
        "paper_code_alignment": alignment.model_dump(),
        "errors": [*state.get("errors", []), *alignment.errors],
    }
