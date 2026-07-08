from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.file_analyze_tool import analyze_files


def file_analyze_node(state: AgentState) -> AgentState:
    if not state.get("parsed_files"):
        return {**state, "file_analysis": []}

    file_analysis = analyze_files(
        repo_index=state.get("repo_index", {}),
        parsed_files=state.get("parsed_files", []),
        classes=state.get("classes", []),
        functions=state.get("functions", []),
    )
    return {
        **state,
        "file_analysis": [item.model_dump() for item in file_analysis],
    }

