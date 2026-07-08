from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    zip_path: str
    paper_pdf_path: str
    repo_path: str
    output_dir: str

    file_tree: dict
    python_files: list[str]
    repo_index: dict

    parsed_files: list[dict]
    functions: list[dict]
    classes: list[dict]
    file_analysis: list[dict]
    library_calls: list[dict]
    low_confidence_library_calls: list[dict]
    function_analysis: list[dict]
    model_analysis: list[dict]
    paper_analysis: dict
    paper_code_alignment: dict
    diagrams: list[dict]
    diagram_warnings: list[str]
    library_db_path: str
    library_function_docs: list[dict]
    new_library_functions: list[dict]
    skipped_low_confidence_library_calls: list[dict]

    report_md: str
    errors: list[dict]
