from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.library_function import LibraryFunctionDoc
from backend.app.services.library_function_service import LibraryFunctionService
from tests.test_library_function_service import _torch_linear_call, _torch_randn_call


client = TestClient(app)


def _seed_library(db_path):
    service = LibraryFunctionService(db_path)
    service.process_library_calls([_torch_randn_call()], task_id="task-a", project_name="demo")
    service.process_library_calls([_torch_randn_call()], task_id="task-b", project_name="demo")
    service.process_library_calls([_torch_linear_call()], task_id="task-a", project_name="demo")
    service.upsert_library_function_doc(
        LibraryFunctionDoc(
            canonical_name="numpy.mystery",
            display_name="numpy.mystery",
            package_name="numpy",
            category="numpy",
            summary="Low confidence function.",
            beginner_explanation="This is a low confidence function for API tests.",
            confidence="low",
        )
    )


def test_list_library_functions_supports_search_filters_and_pagination(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    _seed_library(db_path)

    response = client.get(
        "/library/functions",
        params={
            "library_db_path": str(db_path),
            "query": "randn",
            "package_name": "torch",
            "category": "pytorch",
            "confidence": "high",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_name"] == "torch.randn"
    assert "torch" in body["filters"]["packages"]


def test_library_function_detail(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    _seed_library(db_path)

    detail_response = client.get("/library/functions/torch.randn", params={"library_db_path": str(db_path)})
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["function"]["canonical_name"] == "torch.randn"


def test_library_function_detail_returns_404_for_missing_doc(tmp_path):
    response = client.get("/library/functions/torch.missing", params={"library_db_path": str(tmp_path / "library.sqlite3")})

    assert response.status_code == 404


def test_library_stats_and_low_confidence_endpoint(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    _seed_library(db_path)

    stats_response = client.get("/library/stats", params={"library_db_path": str(db_path)})
    assert stats_response.status_code == 200
    assert stats_response.json()["function_count"] == 3

    low_response = client.get("/library/functions/low-confidence", params={"library_db_path": str(db_path)})
    assert low_response.status_code == 200
    assert low_response.json()["items"][0]["canonical_name"] == "numpy.mystery"


def test_library_functions_rejects_unknown_sort(tmp_path):
    response = client.get(
        "/library/functions",
        params={"library_db_path": str(tmp_path / "library.sqlite3"), "sort": "bad"},
    )

    assert response.status_code == 400
