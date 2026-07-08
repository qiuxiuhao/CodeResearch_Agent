from __future__ import annotations

import sqlite3

from backend.app.schemas.library_function import LibraryFunctionDoc
from backend.app.services.library_function_service import LibraryFunctionService


def _torch_randn_call() -> dict:
    return {
        "file_path": "train.py",
        "class_name": None,
        "function_name": "build_batch",
        "qualified_function_name": "build_batch",
        "canonical_name": "torch.randn",
        "display_name": "torch.randn",
        "package_name": "torch",
        "category": "pytorch",
        "call_text": "torch.randn(2, 3)",
        "line_no": 12,
        "confidence": "high",
        "is_recorded_in_global_library": False,
    }


def _torch_linear_call() -> dict:
    return {
        "file_path": "models/simple_model.py",
        "class_name": "SimpleNet",
        "function_name": "__init__",
        "qualified_function_name": "SimpleNet.__init__",
        "canonical_name": "torch.nn.Linear",
        "display_name": "nn.Linear",
        "package_name": "torch",
        "category": "pytorch",
        "call_text": "nn.Linear(128, 10)",
        "line_no": 9,
        "confidence": "high",
        "is_recorded_in_global_library": False,
    }


def test_process_library_calls_creates_doc_and_occurrence(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")

    result = service.process_library_calls([_torch_randn_call()], task_id="task-a", project_name="demo")

    assert len(result.library_function_docs) == 1
    assert len(result.new_library_functions) == 1
    assert result.updated_library_calls[0]["is_recorded_in_global_library"] is True

    doc = service.get_by_canonical_name("torch.randn")
    assert doc is not None
    assert any("size" in item for item in doc.parameters_explanation)
    assert doc.common_mistakes

    occurrences = service.list_occurrences("torch.randn")
    assert len(occurrences) == 1
    assert occurrences[0].task_id == "task-a"
    assert occurrences[0].file_path == "train.py"
    assert occurrences[0].function_name == "build_batch"
    assert occurrences[0].line_no == 12
    assert occurrences[0].call_text == "torch.randn(2, 3)"


def test_torch_linear_uses_special_teaching_template(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")

    result = service.process_library_calls([_torch_linear_call()], task_id="task-a", project_name="demo")

    doc = result.library_function_docs[0]
    assert "全连接层" in doc.summary
    assert "常用于 PyTorch 张量" not in doc.summary
    assert any("in_features" in item for item in doc.parameters_explanation)
    assert any("out_features" in item for item in doc.parameters_explanation)
    assert doc.return_explanation and "Linear" in doc.return_explanation
    assert doc.common_usage and "深度学习" in doc.common_usage
    assert doc.code_example and "out_features" in doc.code_example
    assert doc.shape_or_tensor_note and "in_features" in doc.shape_or_tensor_note


def test_existing_doc_is_reused_but_occurrences_are_recorded_per_task(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    service = LibraryFunctionService(db_path)

    service.process_library_calls([_torch_randn_call()], task_id="task-a", project_name="demo")
    second_result = service.process_library_calls([_torch_randn_call()], task_id="task-b", project_name="demo")

    assert len(second_result.library_function_docs) == 1
    assert second_result.new_library_functions == []
    assert len(service.list_occurrences("torch.randn")) == 2

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM library_functions WHERE canonical_name = ?", ("torch.randn",)).fetchone()[0]
    assert count == 1


def test_duplicate_occurrence_in_same_task_is_deduplicated(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")

    service.process_library_calls([_torch_randn_call(), _torch_randn_call()], task_id="task-a", project_name="demo")

    assert len(service.list_occurrences("torch.randn")) == 1


def test_low_confidence_or_unknown_calls_are_skipped(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")
    unknown_call = {
        **_torch_randn_call(),
        "canonical_name": "client.call",
        "display_name": "client.call",
        "package_name": None,
        "category": "unknown",
        "confidence": "low",
    }

    result = service.process_library_calls([unknown_call], task_id="task-a", project_name="demo")

    assert result.library_function_docs == []
    assert result.new_library_functions == []
    assert len(result.skipped_low_confidence_calls) == 1
    assert result.updated_library_calls[0]["is_recorded_in_global_library"] is False
    assert service.get_by_canonical_name("client.call") is None


def test_search_functions_filters_and_sorts_by_occurrence_count(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")
    service.process_library_calls([_torch_randn_call()], task_id="task-a", project_name="demo")
    service.process_library_calls([_torch_randn_call()], task_id="task-b", project_name="demo")
    service.process_library_calls([_torch_linear_call()], task_id="task-a", project_name="demo")

    response = service.search_functions(query="randn", package_name="torch", category="pytorch")

    assert response["total"] == 1
    assert response["items"][0]["canonical_name"] == "torch.randn"
    assert response["items"][0]["occurrence_count"] == 2
    assert "torch" in response["filters"]["packages"]
    assert "pytorch" in response["filters"]["categories"]

    sorted_response = service.search_functions(sort="occurrence_count")
    assert [item["canonical_name"] for item in sorted_response["items"]][:2] == [
        "torch.randn",
        "torch.nn.Linear",
    ]


def test_function_detail_stats_and_occurrence_pagination(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")
    service.process_library_calls([_torch_randn_call()], task_id="task-a", project_name="demo")
    service.process_library_calls([_torch_randn_call()], task_id="task-b", project_name="demo")

    detail = service.get_function_detail_with_stats("torch.randn")
    assert detail is not None
    assert detail["function"]["canonical_name"] == "torch.randn"
    assert detail["occurrence_count"] == 2
    assert detail["first_seen"]
    assert detail["last_seen"]

    occurrences = service.list_occurrences("torch.randn", limit=1, offset=1)
    assert len(occurrences) == 1
    assert service.count_occurrences("torch.randn") == 2


def test_library_stats_high_frequency_and_low_confidence(tmp_path):
    service = LibraryFunctionService(tmp_path / "library.sqlite3")
    service.process_library_calls([_torch_randn_call()], task_id="task-a", project_name="demo")
    service.process_library_calls([_torch_randn_call()], task_id="task-b", project_name="demo")
    service.process_library_calls([_torch_linear_call()], task_id="task-a", project_name="demo")
    low_doc = service.upsert_library_function_doc(
        LibraryFunctionDoc(
            canonical_name="numpy.mystery",
            display_name="numpy.mystery",
            package_name="numpy",
            category="numpy",
            summary="Low confidence test function.",
            beginner_explanation="Used only for test coverage.",
            confidence="low",
        )
    )
    service.record_occurrence(
        low_doc,
        {
            **_torch_randn_call(),
            "canonical_name": "numpy.mystery",
            "display_name": "numpy.mystery",
            "package_name": "numpy",
            "category": "numpy",
            "confidence": "low",
        },
        task_id="task-low",
        project_name="demo",
    )

    stats = service.get_library_stats()
    assert stats["function_count"] == 3
    assert stats["occurrence_count"] == 4
    assert any(item["name"] == "torch" and item["count"] == 2 for item in stats["package_counts"])

    high_frequency = service.list_high_frequency_functions()
    assert high_frequency[0]["canonical_name"] == "torch.randn"
    assert high_frequency[0]["occurrence_count"] == 2

    low_confidence = service.list_low_confidence_functions()
    assert [item["canonical_name"] for item in low_confidence] == ["numpy.mystery"]
