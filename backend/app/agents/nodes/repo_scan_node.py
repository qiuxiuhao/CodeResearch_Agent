from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.repo_scan_tool import scan_repository


def repo_scan_node(state: AgentState) -> AgentState:
    if not state.get("repo_path"):
        return {
            **state,
            "file_tree": {},
            "python_files": [],
            "repo_index": {
                "task_id": state.get("task_id"),
                "repo_path": "",
                "file_tree": {},
                "python_files": [],
                "entry_file_candidates": [],
                "model_file_candidates": [],
                "train_file_candidates": [],
                "infer_file_candidates": [],
                "config_file_candidates": [],
                "skipped_files": [],
            },
        }

    repo_index = scan_repository(state["repo_path"], task_id=state.get("task_id"))
    repo_index_dict = repo_index.model_dump()
    previous_skipped = state.get("repo_index", {}).get("skipped_files", [])
    if previous_skipped:
        repo_index_dict["skipped_files"] = [*previous_skipped, *repo_index_dict.get("skipped_files", [])]

    return {
        **state,
        "file_tree": repo_index_dict["file_tree"],
        "python_files": repo_index_dict["python_files"],
        "repo_index": repo_index_dict,
    }
