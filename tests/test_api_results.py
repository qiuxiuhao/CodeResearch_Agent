from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_list_and_get_analysis_task_result(tmp_path):
    task_dir = tmp_path / "task_abc123"
    task_dir.mkdir()
    _write_json(task_dir / "repo_index.json", {"python_files": ["main.py"]})
    _write_json(task_dir / "parsed_files.json", {"classes": [], "functions": [], "parsed_files": []})
    _write_json(task_dir / "file_analysis.json", {"file_analysis": []})
    _write_json(task_dir / "library_calls.json", {"library_calls": []})
    _write_json(task_dir / "function_analysis.json", {"function_analysis": []})
    _write_json(task_dir / "model_analysis.json", {"model_analysis": []})
    _write_json(task_dir / "paper_analysis.json", {"paper_analysis": {"paper_provided": False}})
    _write_json(task_dir / "paper_code_alignment.json", {"paper_code_alignment": {"paper_provided": False}})
    _write_json(task_dir / "diagrams.json", {"diagrams": []})
    _write_json(task_dir / "library_function_docs.json", {"library_function_docs": []})
    (task_dir / "report.md").write_text("# report", encoding="utf-8")

    list_response = client.get("/analysis/tasks", params={"output_root": str(tmp_path)})
    assert list_response.status_code == 200
    assert list_response.json()["tasks"][0]["task_id"] == "task_abc123"

    result_response = client.get("/analysis/tasks/task_abc123", params={"output_root": str(tmp_path)})
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["task_id"] == "task_abc123"
    assert body["repo_index"]["python_files"] == ["main.py"]
    assert body["report_md"] == "# report"

    report_response = client.get("/analysis/tasks/task_abc123/report", params={"output_root": str(tmp_path)})
    assert report_response.status_code == 200
    assert report_response.json()["report_md"] == "# report"


def test_get_analysis_task_rejects_invalid_task_id(tmp_path):
    response = client.get("/analysis/tasks/../secret", params={"output_root": str(tmp_path)})

    assert response.status_code == 404

    response = client.get("/analysis/tasks/notatask", params={"output_root": str(tmp_path)})

    assert response.status_code == 400


def test_get_analysis_task_reports_missing_files(tmp_path):
    (tmp_path / "task_abc999").mkdir()

    response = client.get("/analysis/tasks/task_abc999", params={"output_root": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["errors"]
