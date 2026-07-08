from __future__ import annotations

from backend.app.tools.file_analyze_tool import analyze_files


def test_analyze_files_classifies_python_files():
    repo_index = {
        "python_files": [
            "data/dataset.py",
            "main.py",
            "models/__init__.py",
            "models/simple_model.py",
            "train.py",
        ],
        "entry_file_candidates": ["main.py"],
        "model_file_candidates": ["models/simple_model.py"],
        "train_file_candidates": ["train.py"],
        "infer_file_candidates": [],
    }
    parsed_files = [
        {
            "file_path": "data/dataset.py",
            "imports": [],
            "classes": [{"file_path": "data/dataset.py", "class_name": "TinyDataset", "base_classes": []}],
            "functions": [
                {"file_path": "data/dataset.py", "class_name": "TinyDataset", "function_name": "__len__"},
                {"file_path": "data/dataset.py", "class_name": "TinyDataset", "function_name": "__getitem__"},
            ],
            "errors": [],
        },
        {
            "file_path": "main.py",
            "imports": [{"module": "models.simple_model", "name": "SimpleNet"}],
            "classes": [],
            "functions": [{"file_path": "main.py", "class_name": None, "function_name": "main"}],
            "errors": [],
        },
        {
            "file_path": "models/__init__.py",
            "imports": [{"module": ".simple_model", "name": "SimpleNet"}],
            "classes": [],
            "functions": [],
            "errors": [],
        },
        {
            "file_path": "models/simple_model.py",
            "imports": [{"module": "torch.nn"}, {"module": "torch.nn.functional"}],
            "classes": [{"file_path": "models/simple_model.py", "class_name": "SimpleNet", "base_classes": ["nn.Module"]}],
            "functions": [
                {"file_path": "models/simple_model.py", "class_name": "SimpleNet", "function_name": "__init__"},
                {"file_path": "models/simple_model.py", "class_name": "SimpleNet", "function_name": "forward"},
            ],
            "errors": [],
        },
        {
            "file_path": "train.py",
            "imports": [{"module": "torch"}],
            "classes": [],
            "functions": [{"file_path": "train.py", "class_name": None, "function_name": "train_one_epoch"}],
            "errors": [],
        },
    ]
    classes = [class_info for parsed in parsed_files for class_info in parsed["classes"]]
    functions = [function for parsed in parsed_files for function in parsed["functions"]]

    analyses = analyze_files(repo_index, parsed_files, classes, functions)
    by_path = {item.file_path: item for item in analyses}

    assert by_path["main.py"].file_type == "entry"
    assert by_path["models/simple_model.py"].file_type == "model"
    assert by_path["models/__init__.py"].file_type == "package_init"
    assert not by_path["models/__init__.py"].is_model_file
    assert by_path["train.py"].file_type == "training"
    assert by_path["data/dataset.py"].file_type == "dataset"

    assert by_path["models/simple_model.py"].main_classes == ["SimpleNet"]
    assert by_path["models/simple_model.py"].main_functions == ["SimpleNet.__init__", "SimpleNet.forward"]
    assert by_path["models/simple_model.py"].purpose
    assert by_path["models/simple_model.py"].project_position
    assert by_path["models/simple_model.py"].evidence
    assert "文件位于 model_file_candidates 中" in by_path["models/simple_model.py"].evidence
    assert "类 SimpleNet 继承 nn.Module 或 torch.nn.Module" in by_path["models/simple_model.py"].evidence
    assert by_path["models/simple_model.py"].confidence == "high"
