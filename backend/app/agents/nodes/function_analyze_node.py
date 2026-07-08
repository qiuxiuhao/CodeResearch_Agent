from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.function_analyze_tool import analyze_functions


def function_analyze_node(state: AgentState) -> AgentState:
    function_analysis = analyze_functions(
        functions=state.get("functions", []),
        file_analysis=state.get("file_analysis", []),
        library_calls=state.get("library_calls", []),
    )
    return {
        **state,
        "function_analysis": [item.model_dump() for item in function_analysis],
    }

