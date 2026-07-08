from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from backend.app.agents.graph import build_analysis_graph
from backend.app.schemas.state import AgentState
from backend.app.services.storage_service import ensure_output_root


def run_analysis(
    zip_path: str | Path,
    output_root: str | Path = "outputs",
    library_db_path: str | Path | None = None,
    paper_pdf_path: str | Path | None = None,
) -> AgentState:
    ensure_output_root(output_root)
    resolved_library_db_path = str(library_db_path or os.getenv("LIBRARY_DB_PATH") or "data/python_function_library.sqlite3")
    graph = build_analysis_graph()
    initial_state: AgentState = {
        "zip_path": str(zip_path),
        "output_dir": str(output_root),
        "library_db_path": resolved_library_db_path,
        "errors": [],
    }
    if paper_pdf_path:
        initial_state["paper_pdf_path"] = str(paper_pdf_path)
    return graph.invoke(initial_state)


def summarize_state(state: AgentState) -> dict[str, Any]:
    output_dir = state.get("output_dir", "")
    return {
        "task_id": state.get("task_id"),
        "output_dir": output_dir,
        "repo_index_path": str(Path(output_dir) / "repo_index.json") if output_dir else None,
        "parsed_files_path": str(Path(output_dir) / "parsed_files.json") if output_dir else None,
        "file_analysis_path": str(Path(output_dir) / "file_analysis.json") if output_dir else None,
        "library_calls_path": str(Path(output_dir) / "library_calls.json") if output_dir else None,
        "function_analysis_path": str(Path(output_dir) / "function_analysis.json") if output_dir else None,
        "model_analysis_path": str(Path(output_dir) / "model_analysis.json") if output_dir else None,
        "paper_analysis_path": str(Path(output_dir) / "paper_analysis.json") if output_dir else None,
        "paper_code_alignment_path": str(Path(output_dir) / "paper_code_alignment.json") if output_dir else None,
        "library_function_docs_path": str(Path(output_dir) / "library_function_docs.json") if output_dir else None,
        "report_path": str(Path(output_dir) / "report.md") if output_dir else None,
        "library_db_path": state.get("library_db_path"),
        "paper_pdf_path": state.get("paper_pdf_path"),
        "paper_provided": bool(state.get("paper_analysis", {}).get("paper_provided")),
        "python_file_count": len(state.get("python_files", [])),
        "class_count": len(state.get("classes", [])),
        "function_count": len(state.get("functions", [])),
        "library_call_count": len(state.get("library_calls", [])),
        "library_function_doc_count": len(state.get("library_function_docs", [])),
        "function_analysis_count": len(state.get("function_analysis", [])),
        "model_count": len(state.get("model_analysis", [])),
        "main_model_count": len([
            item for item in state.get("model_analysis", []) if item.get("is_main_model_candidate")
        ]),
        "paper_contribution_count": len(state.get("paper_analysis", {}).get("contributions", [])),
        "paper_alignment_count": len([
            item
            for item in state.get("paper_code_alignment", {}).get("alignment_items", [])
            if item.get("status") == "matched"
        ]),
        "paper_unmatched_count": len(state.get("paper_code_alignment", {}).get("unmatched_contributions", [])),
        "error_count": len(state.get("errors", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CodeResearch Agent repository analysis.")
    parser.add_argument("zip_path", help="Path to a local project ZIP file.")
    parser.add_argument("--output-root", default="outputs", help="Directory for task outputs.")
    parser.add_argument("--library-db-path", default=None, help="Path to the global library function SQLite DB.")
    parser.add_argument("--paper-pdf-path", default=None, help="Optional path to a paper PDF for paper/code alignment.")
    args = parser.parse_args()

    state = run_analysis(args.zip_path, args.output_root, args.library_db_path, args.paper_pdf_path)
    print(json.dumps(summarize_state(state), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
