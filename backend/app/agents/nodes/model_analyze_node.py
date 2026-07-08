from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.model_detect_tool import detect_models


def model_analyze_node(state: AgentState) -> AgentState:
    model_analysis = detect_models(
        parsed_files=state.get("parsed_files", []),
        classes=state.get("classes", []),
        functions=state.get("functions", []),
        file_analysis=state.get("file_analysis", []),
        library_calls=state.get("library_calls", []),
        function_analysis=state.get("function_analysis", []),
    )
    return {
        **state,
        "model_analysis": [item.model_dump() for item in model_analysis],
    }
