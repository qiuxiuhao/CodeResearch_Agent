from __future__ import annotations

from pathlib import Path

from backend.app.schemas.state import AgentState
from backend.app.tools.report_tool import generate_report
from backend.app.utils.json_utils import save_json


def report_generate_node(state: AgentState) -> AgentState:
    output_dir = Path(state["output_dir"])
    repo_index = state.get("repo_index", {})
    parsed_files = state.get("parsed_files", [])
    functions = state.get("functions", [])
    classes = state.get("classes", [])
    file_analysis = state.get("file_analysis", [])
    library_calls = state.get("library_calls", [])
    low_confidence_library_calls = state.get("low_confidence_library_calls", [])
    function_analysis = state.get("function_analysis", [])
    model_analysis = state.get("model_analysis", [])
    paper_analysis = state.get("paper_analysis", {})
    paper_code_alignment = state.get("paper_code_alignment", {})
    library_function_docs = state.get("library_function_docs", [])
    new_library_functions = state.get("new_library_functions", [])
    skipped_low_confidence_library_calls = state.get("skipped_low_confidence_library_calls", [])
    errors = state.get("errors", [])

    save_json(output_dir / "repo_index.json", repo_index)
    save_json(
        output_dir / "parsed_files.json",
        {
            "parsed_files": parsed_files,
            "classes": classes,
            "functions": functions,
            "errors": errors,
        },
    )
    save_json(output_dir / "file_analysis.json", {"file_analysis": file_analysis, "errors": errors})
    save_json(
        output_dir / "library_calls.json",
        {
            "library_calls": library_calls,
            "low_confidence_library_calls": low_confidence_library_calls,
            "errors": errors,
        },
    )
    save_json(output_dir / "function_analysis.json", {"function_analysis": function_analysis, "errors": errors})
    save_json(output_dir / "model_analysis.json", {"model_analysis": model_analysis, "errors": errors})
    save_json(output_dir / "paper_analysis.json", {"paper_analysis": paper_analysis, "errors": errors})
    save_json(
        output_dir / "paper_code_alignment.json",
        {"paper_code_alignment": paper_code_alignment, "errors": errors},
    )
    save_json(
        output_dir / "library_function_docs.json",
        {
            "library_function_docs": library_function_docs,
            "new_library_functions": new_library_functions,
            "skipped_low_confidence_calls": skipped_low_confidence_library_calls,
            "errors": errors,
        },
    )
    report = generate_report(
        output_dir,
        repo_index,
        parsed_files,
        functions,
        classes,
        errors,
        file_analysis,
        function_analysis,
        model_analysis,
        paper_analysis,
        paper_code_alignment,
        library_calls,
        library_function_docs,
        skipped_low_confidence_library_calls,
    )
    return {**state, "report_md": report.report_md}
