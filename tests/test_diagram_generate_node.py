from __future__ import annotations

from backend.app.agents.nodes.diagram_generate_node import diagram_generate_node


def test_diagram_generate_node_writes_diagrams_and_preserves_state():
    state = {
        "repo_index": {"python_files": ["models/simple_model.py"]},
        "file_analysis": [
            {
                "file_path": "models/simple_model.py",
                "file_type": "model",
                "purpose": "模型文件",
                "main_classes": ["SimpleNet"],
                "main_functions": [],
                "evidence": ["模型文件"],
            }
        ],
        "function_analysis": [],
        "model_analysis": [],
        "paper_analysis": {"paper_provided": False},
        "paper_code_alignment": {"paper_provided": False, "alignment_items": []},
        "library_calls": [],
        "errors": [],
        "custom": "keep-me",
    }

    next_state = diagram_generate_node(state)

    assert next_state["custom"] == "keep-me"
    assert next_state["diagrams"]
    assert next_state["diagrams"][0]["diagram_type"] == "project_structure"
    assert any("未提供论文 PDF" in warning for warning in next_state["diagram_warnings"])
    assert next_state["errors"] == []


def test_diagram_generate_node_handles_empty_input():
    state = {"errors": []}

    next_state = diagram_generate_node(state)

    assert next_state["diagrams"] == []
    assert next_state["diagram_warnings"]
    assert next_state["errors"] == []
