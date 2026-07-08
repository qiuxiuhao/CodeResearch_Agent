from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.unzip_tool import unzip_project


def unzip_node(state: AgentState) -> AgentState:
    result = unzip_project(
        zip_path=state["zip_path"],
        output_root=state.get("output_dir", "outputs"),
        task_id=state.get("task_id"),
    )
    next_state: AgentState = {
        **state,
        "task_id": result.task_id,
        "output_dir": result.output_dir,
        "errors": [*state.get("errors", []), *result.errors],
    }
    if result.repo_path:
        next_state["repo_path"] = result.repo_path
    if result.skipped_files:
        next_state.setdefault("repo_index", {})
        next_state["repo_index"]["skipped_files"] = result.skipped_files
    return next_state

