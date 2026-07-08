from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.library_call_extractor_tool import extract_library_calls


def library_call_extract_node(state: AgentState) -> AgentState:
    result = extract_library_calls(
        parsed_files=state.get("parsed_files", []),
        functions=state.get("functions", []),
        classes=state.get("classes", []),
    )
    return {
        **state,
        "library_calls": result.library_calls,
        "low_confidence_library_calls": result.low_confidence_library_calls,
    }

