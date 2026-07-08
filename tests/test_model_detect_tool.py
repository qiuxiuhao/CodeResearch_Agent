from __future__ import annotations

from backend.app.tools.ast_parse_tool import parse_python_file
from backend.app.tools.model_detect_tool import detect_models


def _parse_source(tmp_path, source: str, file_name: str = "models/simple_model.py") -> tuple[list[dict], list[dict], list[dict]]:
    file_path = tmp_path / file_name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(source, encoding="utf-8")
    parsed = parse_python_file(file_path, tmp_path)
    parsed_dict = parsed.model_dump()
    return (
        [parsed_dict],
        [item.model_dump() for item in parsed.classes],
        [item.model_dump() for item in parsed.functions],
    )


def test_detect_models_extracts_nn_module_layers_and_forward_steps(tmp_path):
    parsed_files, classes, functions = _parse_source(
        tmp_path,
        "\n".join(
            [
                "import torch.nn as nn",
                "import torch.nn.functional as F",
                "",
                "class SimpleNet(nn.Module):",
                "    def __init__(self, input_dim, hidden_dim, output_dim):",
                "        super().__init__()",
                "        self.fc1 = nn.Linear(input_dim, hidden_dim)",
                "        self.fc2 = nn.Linear(hidden_dim, output_dim)",
                "",
                "    def forward(self, x):",
                "        hidden = F.relu(self.fc1(x))",
                "        return self.fc2(hidden)",
            ]
        ),
    )

    models = detect_models(
        parsed_files=parsed_files,
        classes=classes,
        functions=functions,
        file_analysis=[{"file_path": "models/simple_model.py", "file_type": "model"}],
        library_calls=[],
        function_analysis=[],
    )

    assert len(models) == 1
    model = models[0]
    assert model.class_name == "SimpleNet"
    assert model.is_nn_module is True
    assert model.is_main_model_candidate is True
    assert model.model_inputs == ["x"]
    assert model.model_outputs == ["self.fc2(hidden)"]
    assert {layer.name for layer in model.layers} == {"fc1", "fc2"}
    assert {layer.layer_type for layer in model.layers} == {"torch.nn.Linear"}
    assert any("self.fc1" in step.uses_layers for step in model.forward_steps)
    assert any("torch.nn.functional.relu" in step.calls for step in model.forward_steps)
    assert any(candidate.name == "self.fc1" and candidate.role == "head" for candidate in model.component_candidates)


def test_detect_models_ignores_non_module_classes(tmp_path):
    parsed_files, classes, functions = _parse_source(
        tmp_path,
        "\n".join(
            [
                "class Helper:",
                "    def __init__(self):",
                "        self.value = 1",
                "",
                "    def forward(self, x):",
                "        return x",
            ]
        ),
        "utils/helper.py",
    )

    models = detect_models(parsed_files, classes, functions, [], [], [])

    assert models == []


def test_linear_layers_are_not_unconditionally_classifiers(tmp_path):
    parsed_files, classes, functions = _parse_source(
        tmp_path,
        "\n".join(
            [
                "import torch.nn as nn",
                "",
                "class ProjectionNet(nn.Module):",
                "    def __init__(self):",
                "        super().__init__()",
                "        self.proj = nn.Linear(4, 4)",
                "        self.classifier = nn.Linear(4, 2)",
                "        self.output_layer = nn.Linear(2, 1)",
                "        self.hidden = nn.Linear(4, 4)",
                "",
                "    def forward(self, x):",
                "        x = self.proj(x)",
                "        x = self.classifier(x)",
                "        return self.output_layer(x)",
            ]
        ),
    )

    models = detect_models(
        parsed_files=parsed_files,
        classes=classes,
        functions=functions,
        file_analysis=[{"file_path": "models/simple_model.py", "file_type": "model"}],
        library_calls=[],
        function_analysis=[],
    )

    layers_by_name = {layer.name: layer for layer in models[0].layers}
    assert layers_by_name["classifier"].role == "classifier"
    assert layers_by_name["output_layer"].role == "classifier"
    assert layers_by_name["proj"].role == "head"
    assert layers_by_name["hidden"].role == "unknown"
    assert any("可能是线性映射层" in item for item in layers_by_name["hidden"].evidence)


def test_detect_models_recognizes_outer_sequential_layer(tmp_path):
    parsed_files, classes, functions = _parse_source(
        tmp_path,
        "\n".join(
            [
                "import torch.nn as nn",
                "",
                "class SequentialNet(nn.Module):",
                "    def __init__(self):",
                "        super().__init__()",
                "        self.encoder = nn.Sequential(nn.Linear(4, 8), nn.ReLU())",
                "",
                "    def forward(self, x):",
                "        return self.encoder(x)",
            ]
        ),
    )

    models = detect_models(
        parsed_files=parsed_files,
        classes=classes,
        functions=functions,
        file_analysis=[{"file_path": "models/simple_model.py", "file_type": "model"}],
        library_calls=[],
        function_analysis=[],
    )

    assert models[0].layers[0].assigned_name == "self.encoder"
    assert models[0].layers[0].layer_type == "torch.nn.Sequential"
    assert "nn.Linear(4, 8)" in models[0].layers[0].call_text


def test_detect_models_records_warning_for_branching_forward(tmp_path):
    parsed_files, classes, functions = _parse_source(
        tmp_path,
        "\n".join(
            [
                "import torch.nn as nn",
                "",
                "class BranchNet(nn.Module):",
                "    def __init__(self):",
                "        super().__init__()",
                "        self.fc = nn.Linear(4, 2)",
                "",
                "    def forward(self, x):",
                "        if x is not None:",
                "            x = self.fc(x)",
                "        return x",
            ]
        ),
    )

    models = detect_models(parsed_files, classes, functions, [{"file_path": "models/simple_model.py", "file_type": "model"}], [], [])

    assert len(models) == 1
    assert any("分支或循环" in warning for warning in models[0].warnings)
    assert any("self.fc" in step.uses_layers for step in models[0].forward_steps)
