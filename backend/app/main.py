from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.services.analysis_service import (
    list_task_summaries,
    load_task_report,
    load_task_result,
    run_analysis,
    summarize_state,
)


app = FastAPI(title="CodeResearch Agent", version="0.8.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalysisTaskRequest(BaseModel):
    zip_path: str
    output_root: str = "outputs"
    library_db_path: str | None = None
    paper_pdf_path: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/analysis/tasks")
def list_analysis_tasks(output_root: str = "outputs") -> dict:
    return {"tasks": list_task_summaries(output_root)}


@app.post("/analysis/tasks")
def create_analysis_task(request: AnalysisTaskRequest) -> dict:
    state = run_analysis(request.zip_path, request.output_root, request.library_db_path, request.paper_pdf_path)
    return summarize_state(state)


@app.post("/analysis/tasks/upload")
async def create_analysis_task_from_upload(
    zip_file: UploadFile = File(...),
    paper_pdf: UploadFile | None = File(None),
    output_root: str = Form("outputs"),
    library_db_path: str | None = Form(None),
) -> dict:
    if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip_file must be a .zip file.")
    if paper_pdf and paper_pdf.filename and not paper_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="paper_pdf must be a .pdf file.")

    upload_dir = Path(output_root) / "_uploads" / uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / Path(zip_file.filename).name
    zip_path.write_bytes(await zip_file.read())

    paper_pdf_path: Path | None = None
    if paper_pdf and paper_pdf.filename:
        paper_pdf_path = upload_dir / Path(paper_pdf.filename).name
        paper_pdf_path.write_bytes(await paper_pdf.read())

    state = run_analysis(zip_path, output_root, library_db_path, paper_pdf_path)
    return summarize_state(state)


@app.get("/analysis/tasks/{task_id}")
def get_analysis_task_result(task_id: str, output_root: str = "outputs") -> dict:
    try:
        return load_task_result(task_id, output_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/analysis/tasks/{task_id}/report")
def get_analysis_task_report(task_id: str, output_root: str = "outputs") -> dict:
    try:
        return load_task_report(task_id, output_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
