from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.ast_parse_tool import parse_python_files


def code_parse_node(state: AgentState) -> AgentState:
    if not state.get("repo_path"):
        return {
            **state,
            "parsed_files": [],
            "functions": [],
            "classes": [],
        }

    parsed_files, functions, classes, parse_errors = parse_python_files(
        repo_path=state["repo_path"],
        python_files=state.get("python_files", []),
    )
    return {
        **state,
        "parsed_files": parsed_files,
        "functions": functions,
        "classes": classes,
        "errors": [*state.get("errors", []), *parse_errors],
    }
