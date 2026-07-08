from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_upload_analysis_task_passes_files_to_run_analysis(monkeypatch, tmp_path):
    captured: dict[str, str | None] = {}

    def fake_run_analysis(zip_path, output_root="outputs", library_db_path=None, paper_pdf_path=None):
        captured["zip_path"] = str(zip_path)
        captured["output_root"] = str(output_root)
        captured["library_db_path"] = str(library_db_path) if library_db_path is not None else None
        captured["paper_pdf_path"] = str(paper_pdf_path) if paper_pdf_path is not None else None
        return {
            "task_id": "taskupload",
            "output_dir": str(tmp_path / "taskupload"),
            "library_db_path": library_db_path,
            "paper_pdf_path": paper_pdf_path,
            "errors": [],
        }

    monkeypatch.setattr("backend.app.main.run_analysis", fake_run_analysis)

    response = client.post(
        "/analysis/tasks/upload",
        data={"output_root": str(tmp_path), "library_db_path": str(tmp_path / "library.sqlite3")},
        files={
            "zip_file": ("project.zip", b"zip-bytes", "application/zip"),
            "paper_pdf": ("paper.pdf", b"pdf-bytes", "application/pdf"),
        },
    )

    assert response.status_code == 200
    assert captured["zip_path"] and captured["zip_path"].endswith("project.zip")
    assert captured["paper_pdf_path"] and captured["paper_pdf_path"].endswith("paper.pdf")
    assert captured["library_db_path"] == str(tmp_path / "library.sqlite3")


def test_upload_analysis_task_rejects_non_zip():
    response = client.post(
        "/analysis/tasks/upload",
        files={"zip_file": ("project.txt", b"text", "text/plain")},
    )

    assert response.status_code == 400


def test_upload_analysis_task_rejects_non_pdf_paper():
    response = client.post(
        "/analysis/tasks/upload",
        files={
            "zip_file": ("project.zip", b"zip-bytes", "application/zip"),
            "paper_pdf": ("paper.txt", b"text", "text/plain"),
        },
    )

    assert response.status_code == 400
