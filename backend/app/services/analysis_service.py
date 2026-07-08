from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.agents.graph import build_analysis_graph
from backend.app.schemas.state import AgentState
from backend.app.services.storage_service import ensure_output_root


def run_analysis(zip_path: str | Path, output_root: str | Path = "outputs") -> AgentState:
    ensure_output_root(output_root)
    graph = build_analysis_graph()
    initial_state: AgentState = {
        "zip_path": str(zip_path),
        "output_dir": str(output_root),
        "errors": [],
    }
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
        "report_path": str(Path(output_dir) / "report.md") if output_dir else None,
        "python_file_count": len(state.get("python_files", [])),
        "class_count": len(state.get("classes", [])),
        "function_count": len(state.get("functions", [])),
        "library_call_count": len(state.get("library_calls", [])),
        "function_analysis_count": len(state.get("function_analysis", [])),
        "error_count": len(state.get("errors", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CodeResearch Agent repository analysis.")
    parser.add_argument("zip_path", help="Path to a local project ZIP file.")
    parser.add_argument("--output-root", default="outputs", help="Directory for task outputs.")
    args = parser.parse_args()

    state = run_analysis(args.zip_path, args.output_root)
    print(json.dumps(summarize_state(state), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
