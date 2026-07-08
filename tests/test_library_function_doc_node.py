from __future__ import annotations

from backend.app.agents.nodes.library_function_doc_node import _project_name, library_function_doc_node


def test_library_function_doc_node_updates_state_and_nested_calls(tmp_path):
    call = {
        "file_path": "models/simple_model.py",
        "class_name": "SimpleNet",
        "function_name": "forward",
        "qualified_function_name": "SimpleNet.forward",
        "canonical_name": "torch.nn.functional.relu",
        "display_name": "F.relu",
        "package_name": "torch",
        "category": "pytorch",
        "call_text": "F.relu(x)",
        "line_no": 20,
        "confidence": "high",
        "is_recorded_in_global_library": False,
    }
    state = {
        "task_id": "task-a",
        "zip_path": "examples/small_pytorch_project.zip",
        "library_db_path": str(tmp_path / "library.sqlite3"),
        "library_calls": [call],
        "function_analysis": [
            {
                "file_path": "models/simple_model.py",
                "qualified_name": "SimpleNet.forward",
                "library_calls": [call],
            }
        ],
        "errors": [],
    }

    next_state = library_function_doc_node(state)

    assert next_state["library_calls"][0]["is_recorded_in_global_library"] is True
    assert next_state["function_analysis"][0]["library_calls"][0]["is_recorded_in_global_library"] is True
    assert next_state["library_function_docs"][0]["canonical_name"] == "torch.nn.functional.relu"
    assert next_state["new_library_functions"][0]["canonical_name"] == "torch.nn.functional.relu"
    assert next_state["skipped_low_confidence_library_calls"] == []


def test_project_name_prefers_zip_stem_over_source_repo_path():
    state = {
        "zip_path": "/tmp/small_pytorch_project.zip",
        "repo_path": "/tmp/output/task-a/source",
    }

    assert _project_name(state) == "small_pytorch_project"
    assert _project_name({"repo_path": "/tmp/output/task-a/source"}) == "source"


def test_library_function_doc_node_skips_low_confidence_calls(tmp_path):
    call = {
        "file_path": "main.py",
        "class_name": None,
        "function_name": "main",
        "qualified_function_name": "main",
        "canonical_name": "client.call",
        "display_name": "client.call",
        "package_name": None,
        "category": "unknown",
        "call_text": "client.call()",
        "line_no": 8,
        "confidence": "low",
        "is_recorded_in_global_library": False,
    }
    state = {
        "task_id": "task-a",
        "library_db_path": str(tmp_path / "library.sqlite3"),
        "library_calls": [call],
        "function_analysis": [{"qualified_name": "main", "library_calls": [call]}],
        "errors": [],
    }

    next_state = library_function_doc_node(state)

    assert next_state["library_function_docs"] == []
    assert next_state["new_library_functions"] == []
    assert len(next_state["skipped_low_confidence_library_calls"]) == 1
    assert next_state["library_calls"][0]["is_recorded_in_global_library"] is False
