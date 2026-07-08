from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from backend.app.agents.graph import build_analysis_graph
from backend.app.schemas.state import AgentState
from backend.app.services.storage_service import ensure_output_root


TASK_ID_PATTERN = re.compile(r"^task_[A-Za-z0-9]+$")
TASK_RESULT_FILES = {
    "repo_index": "repo_index.json",
    "parsed_files": "parsed_files.json",
    "file_analysis": "file_analysis.json",
    "library_calls": "library_calls.json",
    "function_analysis": "function_analysis.json",
    "model_analysis": "model_analysis.json",
    "paper_analysis": "paper_analysis.json",
    "paper_code_alignment": "paper_code_alignment.json",
    "diagrams": "diagrams.json",
    "library_function_docs": "library_function_docs.json",
}


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


def list_task_summaries(output_root: str | Path = "outputs", limit: int = 50) -> list[dict[str, Any]]:
    root = Path(output_root)
    if not root.exists():
        return []
    task_dirs = [
        path
        for path in root.iterdir()
        if path.is_dir() and TASK_ID_PATTERN.match(path.name)
    ]
    task_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "task_id": task_dir.name,
            "output_dir": str(task_dir),
            "created_at": None,
            "has_report": (task_dir / "report.md").exists(),
            "has_diagrams": (task_dir / "diagrams.json").exists(),
        }
        for task_dir in task_dirs[:limit]
    ]


def load_task_result(task_id: str, output_root: str | Path = "outputs") -> dict[str, Any]:
    task_dir = _task_output_dir(task_id, output_root)
    errors: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "task_id": task_id,
        "summary": _summarize_output_dir(task_id, task_dir),
        "report_md": _read_report(task_dir, errors),
        "errors": errors,
    }
    for key, filename in TASK_RESULT_FILES.items():
        result[key] = _read_json(task_dir / filename, key, errors)
    return result


def load_task_report(task_id: str, output_root: str | Path = "outputs") -> dict[str, str]:
    task_dir = _task_output_dir(task_id, output_root)
    report_path = task_dir / "report.md"
    if not report_path.exists():
        return {"task_id": task_id, "report_md": ""}
    return {"task_id": task_id, "report_md": report_path.read_text(encoding="utf-8")}


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
        "diagrams_path": str(Path(output_dir) / "diagrams.json") if output_dir else None,
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
        "diagram_count": len(state.get("diagrams", [])),
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


def _task_output_dir(task_id: str, output_root: str | Path) -> Path:
    if not TASK_ID_PATTERN.match(task_id):
        raise ValueError("Invalid task_id.")
    root = Path(output_root)
    task_dir = (root / task_id).resolve()
    root_resolved = root.resolve()
    if root_resolved not in task_dir.parents and task_dir != root_resolved:
        raise ValueError("Invalid task output path.")
    return task_dir


def _read_json(path: Path, key: str, errors: list[dict[str, str]]) -> dict:
    if not path.exists():
        errors.append({"path": str(path), "error_type": "FileNotFoundError", "message": f"Missing {path.name}"})
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append({"path": str(path), "error_type": "JSONDecodeError", "message": str(exc)})
        return {}


def _read_report(task_dir: Path, errors: list[dict[str, str]]) -> str:
    report_path = task_dir / "report.md"
    if not report_path.exists():
        errors.append({"path": str(report_path), "error_type": "FileNotFoundError", "message": "Missing report.md"})
        return ""
    return report_path.read_text(encoding="utf-8")


def _summarize_output_dir(task_id: str, task_dir: Path) -> dict[str, Any]:
    repo_index = _safe_json(task_dir / "repo_index.json")
    parsed_files = _safe_json(task_dir / "parsed_files.json")
    library_calls = _safe_json(task_dir / "library_calls.json")
    function_analysis = _safe_json(task_dir / "function_analysis.json")
    model_analysis = _safe_json(task_dir / "model_analysis.json")
    paper_analysis = _safe_json(task_dir / "paper_analysis.json")
    diagrams = _safe_json(task_dir / "diagrams.json")
    return {
        "task_id": task_id,
        "output_dir": str(task_dir),
        "python_file_count": len(repo_index.get("python_files", [])),
        "class_count": len(parsed_files.get("classes", [])),
        "function_count": len(parsed_files.get("functions", [])),
        "library_call_count": len(library_calls.get("library_calls", [])),
        "function_analysis_count": len(function_analysis.get("function_analysis", [])),
        "model_count": len(model_analysis.get("model_analysis", [])),
        "paper_provided": bool(paper_analysis.get("paper_analysis", {}).get("paper_provided")),
        "diagram_count": len(diagrams.get("diagrams", [])),
    }


def _safe_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


if __name__ == "__main__":
    main()
