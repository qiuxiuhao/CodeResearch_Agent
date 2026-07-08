from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.analysis_service import run_analysis, summarize_state


def test_langgraph_workflow_writes_outputs(tmp_path):
    example_zip = Path("examples/small_pytorch_project.zip")

    state = run_analysis(example_zip, tmp_path / "outputs")
    summary = summarize_state(state)
    output_dir = Path(state["output_dir"])

    assert summary["python_file_count"] >= 5
    assert summary["class_count"] >= 2
    assert summary["function_count"] >= 5
    assert (output_dir / "repo_index.json").exists()
    assert (output_dir / "parsed_files.json").exists()
    assert (output_dir / "report.md").exists()

    repo_index = json.loads((output_dir / "repo_index.json").read_text(encoding="utf-8"))
    parsed_files = json.loads((output_dir / "parsed_files.json").read_text(encoding="utf-8"))

    assert "models/simple_model.py" in repo_index["python_files"]
    assert "data/dataset.py" in repo_index["python_files"]
    assert "models/__init__.py" not in repo_index["model_file_candidates"]
    assert parsed_files["parsed_files"]
    assert parsed_files["classes"]
    assert parsed_files["functions"]
    assert "SimpleNet" in (output_dir / "report.md").read_text(encoding="utf-8")
