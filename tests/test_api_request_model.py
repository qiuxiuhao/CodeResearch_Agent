from __future__ import annotations

from backend.app.main import AnalysisTaskRequest, create_analysis_task


def test_analysis_task_request_supports_library_db_path(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_run_analysis(zip_path, output_root="outputs", library_db_path=None, paper_pdf_path=None):
        captured["zip_path"] = str(zip_path)
        captured["output_root"] = str(output_root)
        captured["library_db_path"] = str(library_db_path) if library_db_path is not None else None
        captured["paper_pdf_path"] = str(paper_pdf_path) if paper_pdf_path is not None else None
        return {
            "task_id": "task-api",
            "output_dir": "/tmp/task-api",
            "library_db_path": library_db_path,
            "paper_pdf_path": paper_pdf_path,
            "errors": [],
        }

    monkeypatch.setattr("backend.app.main.run_analysis", fake_run_analysis)

    request = AnalysisTaskRequest(
        zip_path="examples/small_pytorch_project.zip",
        output_root="/tmp/api-output",
        library_db_path="/tmp/api-library.sqlite3",
        paper_pdf_path="/tmp/paper.pdf",
    )
    result = create_analysis_task(request)

    assert captured == {
        "zip_path": "examples/small_pytorch_project.zip",
        "output_root": "/tmp/api-output",
        "library_db_path": "/tmp/api-library.sqlite3",
        "paper_pdf_path": "/tmp/paper.pdf",
    }
    assert result["library_db_path"] == "/tmp/api-library.sqlite3"
    assert result["paper_pdf_path"] == "/tmp/paper.pdf"
