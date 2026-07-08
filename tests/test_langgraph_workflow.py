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
    assert (output_dir / "file_analysis.json").exists()
    assert (output_dir / "report.md").exists()

    repo_index = json.loads((output_dir / "repo_index.json").read_text(encoding="utf-8"))
    parsed_files = json.loads((output_dir / "parsed_files.json").read_text(encoding="utf-8"))
    file_analysis = json.loads((output_dir / "file_analysis.json").read_text(encoding="utf-8"))
    file_analysis_by_path = {item["file_path"]: item for item in file_analysis["file_analysis"]}

    assert "models/simple_model.py" in repo_index["python_files"]
    assert "data/dataset.py" in repo_index["python_files"]
    assert "models/__init__.py" not in repo_index["model_file_candidates"]
    assert parsed_files["parsed_files"]
    assert parsed_files["classes"]
    assert parsed_files["functions"]
    assert len(file_analysis["file_analysis"]) == len(repo_index["python_files"])
    assert file_analysis_by_path["models/__init__.py"]["file_type"] == "package_init"
    assert file_analysis_by_path["models/simple_model.py"]["file_type"] == "model"
    assert file_analysis_by_path["data/dataset.py"]["file_type"] == "dataset"
    assert file_analysis_by_path["train.py"]["file_type"] == "training"
    assert file_analysis_by_path["main.py"]["file_type"] == "entry"

    report_md = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "SimpleNet" in report_md
    assert "## 逐文件分析" in report_md
    assert "data/dataset.py" in report_md
    assert "models/simple_model.py" in report_md
    assert "train.py" in report_md
