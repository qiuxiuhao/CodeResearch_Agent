from __future__ import annotations

from backend.app.tools.ast_parse_tool import parse_python_file


def test_parse_python_file_extracts_imports_classes_and_functions(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text(
        "\n".join(
            [
                "import numpy as np",
                "from torch.nn import Linear",
                "",
                "class Model(BaseModel):",
                "    def __init__(self, dim):",
                "        self.layer = Linear(dim, dim)",
                "",
                "    def forward(self, x):",
                "        return np.asarray(x)",
                "",
                "def helper(value):",
                "    return value",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_python_file(file_path, tmp_path)

    assert parsed.aliases["np"] == "numpy"
    assert parsed.aliases["Linear"] == "torch.nn.Linear"
    assert parsed.classes[0].class_name == "Model"
    assert parsed.classes[0].methods == ["__init__", "forward"]
    function_names = {(item.class_name, item.function_name) for item in parsed.functions}
    assert ("Model", "__init__") in function_names
    assert ("Model", "forward") in function_names
    assert (None, "helper") in function_names


def test_parse_python_file_records_syntax_errors(tmp_path):
    file_path = tmp_path / "bad.py"
    file_path.write_text("def broken(:\n", encoding="utf-8")

    parsed = parse_python_file(file_path, tmp_path)

    assert parsed.errors
    assert parsed.errors[0]["error_type"] == "SyntaxError"

