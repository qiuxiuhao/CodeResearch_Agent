from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.app.services.analysis_service import run_analysis, summarize_state


def _write_sample_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "SimpleNet Alignment Paper",
                "Abstract",
                "We propose a novel SimpleNet classifier head with relu activation.",
                "Method",
                "The method uses SimpleNet and a classifier head for compact model examples.",
            ]
        ),
    )
    document.save(path)
    document.close()


def test_langgraph_workflow_writes_outputs(tmp_path):
    example_zip = Path("examples/small_pytorch_project.zip")

    state = run_analysis(example_zip, tmp_path / "outputs", tmp_path / "library.sqlite3")
    summary = summarize_state(state)
    output_dir = Path(state["output_dir"])

    assert summary["python_file_count"] >= 5
    assert summary["class_count"] >= 2
    assert summary["function_count"] >= 5
    assert (output_dir / "repo_index.json").exists()
    assert (output_dir / "parsed_files.json").exists()
    assert (output_dir / "file_analysis.json").exists()
    assert (output_dir / "library_calls.json").exists()
    assert (output_dir / "function_analysis.json").exists()
    assert (output_dir / "model_analysis.json").exists()
    assert (output_dir / "paper_analysis.json").exists()
    assert (output_dir / "paper_code_alignment.json").exists()
    assert (output_dir / "paper_figure_analysis.json").exists()
    assert (output_dir / "diagrams.json").exists()
    assert (output_dir / "library_function_docs.json").exists()
    assert (output_dir / "report.md").exists()

    repo_index = json.loads((output_dir / "repo_index.json").read_text(encoding="utf-8"))
    parsed_files = json.loads((output_dir / "parsed_files.json").read_text(encoding="utf-8"))
    file_analysis = json.loads((output_dir / "file_analysis.json").read_text(encoding="utf-8"))
    library_calls = json.loads((output_dir / "library_calls.json").read_text(encoding="utf-8"))
    function_analysis = json.loads((output_dir / "function_analysis.json").read_text(encoding="utf-8"))
    model_analysis = json.loads((output_dir / "model_analysis.json").read_text(encoding="utf-8"))
    paper_analysis = json.loads((output_dir / "paper_analysis.json").read_text(encoding="utf-8"))
    paper_code_alignment = json.loads((output_dir / "paper_code_alignment.json").read_text(encoding="utf-8"))
    paper_figures = json.loads((output_dir / "paper_figure_analysis.json").read_text(encoding="utf-8"))
    diagrams = json.loads((output_dir / "diagrams.json").read_text(encoding="utf-8"))
    library_function_docs = json.loads((output_dir / "library_function_docs.json").read_text(encoding="utf-8"))
    file_analysis_by_path = {item["file_path"]: item for item in file_analysis["file_analysis"]}
    function_analysis_by_name = {item["qualified_name"]: item for item in function_analysis["function_analysis"]}
    library_call_names = {item["canonical_name"] for item in library_calls["library_calls"]}
    model_analysis_by_name = {item["class_name"]: item for item in model_analysis["model_analysis"]}

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
    assert len(function_analysis["function_analysis"]) == len(parsed_files["functions"])
    assert "torch.nn.functional.relu" in library_call_names
    assert "torch.randn" in library_call_names
    assert {item["canonical_name"] for item in library_function_docs["library_function_docs"]} >= {
        "torch.nn.functional.relu",
        "torch.randn",
    }
    assert all(
        item["is_recorded_in_global_library"]
        for item in library_calls["library_calls"]
        if item["canonical_name"] in {"torch.nn.functional.relu", "torch.randn"}
    )
    assert function_analysis_by_name["SimpleNet.forward"]["is_core_function"]
    assert function_analysis_by_name["train_one_epoch"]["is_core_function"]
    assert function_analysis_by_name["SimpleNet.forward"]["library_calls"]
    assert "SimpleNet" in model_analysis_by_name
    assert model_analysis_by_name["SimpleNet"]["is_nn_module"] is True
    assert model_analysis_by_name["SimpleNet"]["is_main_model_candidate"] is True
    assert {layer["name"] for layer in model_analysis_by_name["SimpleNet"]["layers"]} == {"fc1", "fc2"}
    assert model_analysis_by_name["SimpleNet"]["forward_steps"]
    assert any(
        call["is_recorded_in_global_library"]
        for call in function_analysis_by_name["SimpleNet.forward"]["library_calls"]
    )
    assert summary["library_db_path"] == str(tmp_path / "library.sqlite3")
    assert summary["library_function_doc_count"] >= 2
    assert summary["model_count"] >= 1
    assert summary["main_model_count"] == 1
    assert summary["paper_provided"] is False
    assert paper_analysis["paper_analysis"]["paper_provided"] is False
    assert paper_code_alignment["paper_code_alignment"]["paper_provided"] is False
    assert paper_figures["vision_status"] == "disabled"
    assert paper_figures["figures"] == []
    diagram_types = {item["diagram_type"] for item in diagrams["diagrams"]}
    assert "project_structure" in diagram_types
    assert "model_flow" in diagram_types
    assert summary["diagram_count"] == len(diagrams["diagrams"])

    report_md = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "SimpleNet" in report_md
    assert "## 逐文件分析" in report_md
    assert "## 逐函数分析" in report_md
    assert "## 模型网络结构分析" in report_md
    assert "## 论文解析与论文代码对齐" in report_md
    assert "## 图示分析" in report_md
    assert "```mermaid" in report_md
    assert "## Python 库函数说明" in report_md
    assert "self.fc1：head" in report_md
    assert "torch.nn.functional.relu：activation" in report_md
    assert "classifier, classifier" not in report_md
    assert "data/dataset.py" in report_md
    assert "models/simple_model.py" in report_md
    assert "train.py" in report_md


def test_langgraph_workflow_reuses_library_docs_across_runs(tmp_path):
    example_zip = Path("examples/small_pytorch_project.zip")
    db_path = tmp_path / "library.sqlite3"

    run_analysis(example_zip, tmp_path / "outputs-a", db_path)
    with sqlite3.connect(db_path) as conn:
        first_doc_count = conn.execute("SELECT COUNT(*) FROM library_functions").fetchone()[0]

    run_analysis(example_zip, tmp_path / "outputs-b", db_path)
    with sqlite3.connect(db_path) as conn:
        second_doc_count = conn.execute("SELECT COUNT(*) FROM library_functions").fetchone()[0]

    assert first_doc_count >= 1
    assert second_doc_count == first_doc_count


def test_langgraph_workflow_with_paper_pdf_outputs_paper_analysis(tmp_path):
    example_zip = Path("examples/small_pytorch_project.zip")
    pdf_path = tmp_path / "paper.pdf"
    _write_sample_pdf(pdf_path)

    state = run_analysis(example_zip, tmp_path / "outputs", tmp_path / "library.sqlite3", pdf_path)
    summary = summarize_state(state)
    output_dir = Path(state["output_dir"])

    paper_analysis = json.loads((output_dir / "paper_analysis.json").read_text(encoding="utf-8"))
    paper_code_alignment = json.loads((output_dir / "paper_code_alignment.json").read_text(encoding="utf-8"))
    paper_figures = json.loads((output_dir / "paper_figure_analysis.json").read_text(encoding="utf-8"))
    diagrams = json.loads((output_dir / "diagrams.json").read_text(encoding="utf-8"))
    report_md = (output_dir / "report.md").read_text(encoding="utf-8")

    assert summary["paper_provided"] is True
    assert summary["paper_contribution_count"] >= 1
    assert paper_analysis["paper_analysis"]["title"] == "SimpleNet Alignment Paper"
    assert paper_analysis["paper_analysis"]["contributions"]
    assert paper_code_alignment["paper_code_alignment"]["alignment_items"]
    assert paper_figures["extraction_status"] in {"success", "skipped"}
    assert paper_figures["vision_status"] == "disabled"
    assert all("confidence" in item for item in paper_code_alignment["paper_code_alignment"]["alignment_items"])
    assert any(item["diagram_type"] == "paper_code_alignment" for item in diagrams["diagrams"])
    assert "论文解析与论文代码对齐" in report_md
    assert "图示分析" in report_md
    assert "SimpleNet Alignment Paper" in report_md


def test_partial_paper_parse_still_writes_analysis_and_report(monkeypatch, tmp_path):
    import fitz

    pdf_path = tmp_path / "long-paper.pdf"
    document = fitz.open()
    for index in range(3):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {index + 1}\nMethod\nWe propose a model module.")
    document.save(pdf_path)
    document.close()
    monkeypatch.setenv("PAPER_MAX_PAGES", "1")

    state = run_analysis(
        Path("examples/small_pytorch_project.zip"),
        tmp_path / "outputs",
        tmp_path / "library.sqlite3",
        pdf_path,
    )
    output_dir = Path(state["output_dir"])
    paper_payload = json.loads((output_dir / "paper_analysis.json").read_text(encoding="utf-8"))

    assert paper_payload["paper_analysis"]["page_count"] == 1
    assert any("PAPER_MAX_PAGES" in item for item in paper_payload["paper_analysis"]["warnings"])
    assert (output_dir / "report.md").exists()
    assert "图示分析" in (output_dir / "report.md").read_text(encoding="utf-8")
