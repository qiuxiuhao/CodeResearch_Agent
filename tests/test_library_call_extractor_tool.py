from __future__ import annotations

from backend.app.tools.library_call_extractor_tool import extract_library_calls


def test_extract_library_calls_resolves_aliases_and_skips_internal_calls():
    parsed_files = [
        {
            "file_path": "models/simple_model.py",
            "aliases": {"F": "torch.nn.functional"},
        },
        {
            "file_path": "train.py",
            "aliases": {"torch": "torch"},
        },
        {
            "file_path": "main.py",
            "aliases": {
                "SimpleNet": "models.simple_model.SimpleNet",
                "train_one_epoch": "train.train_one_epoch",
            },
        },
    ]
    classes = [{"file_path": "models/simple_model.py", "class_name": "SimpleNet"}]
    functions = [
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "forward",
            "start_line": 11,
            "source_code": "def forward(self, x):\n    hidden = F.relu(self.fc1(x))\n    return self.fc2(hidden)",
        },
        {
            "file_path": "train.py",
            "class_name": None,
            "function_name": "train_one_epoch",
            "start_line": 4,
            "source_code": "def train_one_epoch(model):\n    batch = torch.randn(2, 4)\n    output = model(batch)\n    loss = output.mean()\n    return loss",
        },
        {
            "file_path": "main.py",
            "class_name": None,
            "function_name": "main",
            "start_line": 5,
            "source_code": "def main():\n    model = SimpleNet(4, 8, 2)\n    train_one_epoch(model)",
        },
    ]

    result = extract_library_calls(parsed_files, functions, classes)
    canonical_names = {item["canonical_name"] for item in result.library_calls}
    display_names = {item["display_name"] for item in result.library_calls}

    assert "torch.nn.functional.relu" in canonical_names
    assert "torch.randn" in canonical_names
    assert "SimpleNet" not in canonical_names
    assert "models.simple_model.SimpleNet" not in canonical_names
    assert "train_one_epoch" not in canonical_names
    assert "train.train_one_epoch" not in canonical_names
    assert "SimpleNet" not in display_names
    assert "train_one_epoch" not in display_names
    assert "self.fc1" not in canonical_names
    assert "self.fc2" not in canonical_names


def test_extract_library_calls_keeps_possible_external_unknown_as_low_confidence():
    parsed_files = [{"file_path": "plugin.py", "aliases": {}}]
    functions = [
        {
            "file_path": "plugin.py",
            "class_name": None,
            "function_name": "load_plugin",
            "start_line": 1,
            "source_code": "def load_plugin(x):\n    return external_api.run(x)",
        }
    ]

    result = extract_library_calls(parsed_files, functions, classes=[])

    assert result.library_calls[0]["canonical_name"] == "external_api.run"
    assert result.library_calls[0]["confidence"] == "low"
    assert result.low_confidence_library_calls[0]["canonical_name"] == "external_api.run"
