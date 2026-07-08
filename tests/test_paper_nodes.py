from __future__ import annotations

from pathlib import Path

from backend.app.agents.nodes.paper_analyze_node import paper_analyze_node
from backend.app.agents.nodes.paper_code_align_node import paper_code_align_node


def _write_sample_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "SimpleNet Paper",
                "Abstract",
                "We propose a novel SimpleNet classifier head.",
                "Method",
                "The method uses SimpleNet and relu activation.",
            ]
        ),
    )
    document.save(path)
    document.close()


def test_paper_analyze_node_outputs_empty_without_pdf():
    state = {"errors": [], "repo_index": {"python_files": []}}

    next_state = paper_analyze_node(state)

    assert next_state["paper_analysis"]["paper_provided"] is False
    assert next_state["errors"] == []


def test_paper_nodes_parse_and_align_pdf(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    _write_sample_pdf(pdf_path)
    state = {
        "paper_pdf_path": str(pdf_path),
        "repo_index": {"python_files": ["models/simple_model.py"]},
        "file_analysis": [{"file_path": "models/simple_model.py", "file_type": "model", "purpose": "SimpleNet model"}],
        "classes": [{"file_path": "models/simple_model.py", "class_name": "SimpleNet", "start_line": 5, "base_classes": ["nn.Module"]}],
        "functions": [],
        "function_analysis": [],
        "model_analysis": [{"file_path": "models/simple_model.py", "class_name": "SimpleNet", "layers": [], "component_candidates": []}],
        "library_calls": [],
        "errors": [],
    }

    analyzed = paper_analyze_node(state)
    aligned = paper_code_align_node(analyzed)

    assert analyzed["paper_analysis"]["paper_provided"] is True
    assert analyzed["paper_analysis"]["contributions"]
    assert aligned["paper_code_alignment"]["paper_provided"] is True
    assert aligned["paper_code_alignment"]["alignment_items"]
    assert aligned["repo_index"] == state["repo_index"]
