from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    zip_path: str
    repo_path: str
    output_dir: str

    file_tree: dict
    python_files: list[str]
    repo_index: dict

    parsed_files: list[dict]
    functions: list[dict]
    classes: list[dict]
    file_analysis: list[dict]

    report_md: str
    errors: list[dict]
