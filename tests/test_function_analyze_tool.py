from __future__ import annotations

from backend.app.tools.function_analyze_tool import analyze_functions


def test_analyze_functions_marks_core_functions_and_embeds_library_calls():
    functions = [
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "forward",
            "args": ["self", "x"],
            "start_line": 11,
            "end_line": 13,
            "source_code": "def forward(self, x):\n    hidden = F.relu(self.fc1(x))\n    return self.fc2(hidden)",
            "raw_call_expressions": ["F.relu", "self.fc1", "self.fc2"],
        },
        {
            "file_path": "train.py",
            "class_name": None,
            "function_name": "train_one_epoch",
            "args": ["model"],
            "start_line": 4,
            "end_line": 8,
            "source_code": "def train_one_epoch(model):\n    batch = torch.randn(2, 4)\n    output = model(batch)\n    return batch",
            "raw_call_expressions": ["torch.randn", "model"],
        },
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "__init__",
            "args": ["self"],
            "start_line": 6,
            "end_line": 9,
            "source_code": "def __init__(self):\n    super().__init__()\n    self.fc = nn.Linear(4, 2)",
            "raw_call_expressions": ["super", "super().__init__", "nn.Linear"],
        },
    ]
    file_analysis = [
        {"file_path": "models/simple_model.py", "file_type": "model"},
        {"file_path": "train.py", "file_type": "training"},
    ]
    library_calls = [
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "forward",
            "qualified_function_name": "SimpleNet.forward",
            "canonical_name": "torch.nn.functional.relu",
            "display_name": "F.relu",
            "package_name": "torch",
            "category": "pytorch",
            "call_text": "F.relu(self.fc1(x))",
            "line_no": 12,
            "confidence": "high",
            "is_recorded_in_global_library": False,
        }
    ]

    analyses = analyze_functions(functions, file_analysis, library_calls)
    by_name = {item.qualified_name: item for item in analyses}

    assert by_name["SimpleNet.forward"].is_core_function
    assert by_name["SimpleNet.forward"].library_calls[0].canonical_name == "torch.nn.functional.relu"
    assert by_name["train_one_epoch"].is_core_function
    assert by_name["train_one_epoch"].core_reason
    assert "model" not in by_name["train_one_epoch"].called_internal_functions
    assert "super" not in by_name["SimpleNet.__init__"].called_internal_functions
    assert "super().__init__" not in by_name["SimpleNet.__init__"].called_internal_functions


def test_analyze_functions_deduplicates_computation_logic():
    functions = [
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "forward",
            "args": ["self", "x"],
            "start_line": 1,
            "end_line": 2,
            "source_code": "def forward(self, x):\n    return F.relu(F.relu(x))",
            "raw_call_expressions": ["F.relu", "F.relu"],
        }
    ]
    library_calls = [
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "forward",
            "qualified_function_name": "SimpleNet.forward",
            "canonical_name": "torch.nn.functional.relu",
            "display_name": "F.relu",
            "package_name": "torch",
            "category": "pytorch",
            "call_text": "F.relu(x)",
            "line_no": 2,
            "confidence": "high",
            "is_recorded_in_global_library": False,
        },
        {
            "file_path": "models/simple_model.py",
            "class_name": "SimpleNet",
            "function_name": "forward",
            "qualified_function_name": "SimpleNet.forward",
            "canonical_name": "torch.nn.functional.relu",
            "display_name": "F.relu",
            "package_name": "torch",
            "category": "pytorch",
            "call_text": "F.relu(x)",
            "line_no": 2,
            "confidence": "high",
            "is_recorded_in_global_library": False,
        },
    ]

    analysis = analyze_functions(functions, [{"file_path": "models/simple_model.py", "file_type": "model"}], library_calls)[0]

    assert analysis.computation_logic.count("调用外部库函数 torch.nn.functional.relu。") == 1
