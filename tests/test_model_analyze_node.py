from __future__ import annotations

from backend.app.agents.nodes.model_analyze_node import model_analyze_node
from backend.app.tools.ast_parse_tool import parse_python_file


def test_model_analyze_node_writes_model_analysis(tmp_path):
    file_path = tmp_path / "models" / "simple_model.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        "\n".join(
            [
                "import torch.nn as nn",
                "",
                "class SimpleNet(nn.Module):",
                "    def __init__(self):",
                "        super().__init__()",
                "        self.fc = nn.Linear(4, 2)",
                "",
                "    def forward(self, x):",
                "        return self.fc(x)",
            ]
        ),
        encoding="utf-8",
    )
    parsed = parse_python_file(file_path, tmp_path)
    state = {
        "parsed_files": [parsed.model_dump()],
        "classes": [item.model_dump() for item in parsed.classes],
        "functions": [item.model_dump() for item in parsed.functions],
        "file_analysis": [{"file_path": "models/simple_model.py", "file_type": "model"}],
        "library_calls": [],
        "function_analysis": [],
        "errors": [],
    }

    next_state = model_analyze_node(state)

    assert next_state["model_analysis"]
    assert next_state["model_analysis"][0]["class_name"] == "SimpleNet"
    assert next_state["model_analysis"][0]["is_main_model_candidate"] is True
    assert next_state["errors"] == []


def test_model_analyze_node_returns_empty_analysis_without_models():
    state = {
        "parsed_files": [],
        "classes": [],
        "functions": [],
        "file_analysis": [],
        "library_calls": [],
        "function_analysis": [],
        "errors": [{"message": "keep me"}],
    }

    next_state = model_analyze_node(state)

    assert next_state["model_analysis"] == []
    assert next_state["errors"] == [{"message": "keep me"}]
