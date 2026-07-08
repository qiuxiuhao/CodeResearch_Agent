from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.services.analysis_service import (
    list_task_summaries,
    load_task_report,
    load_task_result,
    run_analysis,
    summarize_state,
)
from backend.app.services.library_function_service import LibraryFunctionService


app = FastAPI(title="CodeResearch Agent", version="1.0.1")
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


@app.get("/library/functions")
def list_library_functions(
    query: str | None = None,
    package_name: str | None = None,
    category: str | None = None,
    confidence: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = "canonical_name",
    library_db_path: str | None = None,
) -> dict:
    try:
        return _library_service(library_db_path).search_functions(
            query=query,
            package_name=package_name,
            category=category,
            confidence=confidence,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/library/stats")
def get_library_stats(library_db_path: str | None = None) -> dict:
    return _library_service(library_db_path).get_library_stats()


@app.get("/library/functions/low-confidence")
def list_low_confidence_library_functions(
    limit: int = Query(50, ge=1, le=100),
    library_db_path: str | None = None,
) -> dict:
    return {"items": _library_service(library_db_path).list_low_confidence_functions(limit)}


@app.get("/library/functions/{canonical_name}")
def get_library_function_detail(canonical_name: str, library_db_path: str | None = None) -> dict:
    detail = _library_service(library_db_path).get_function_detail(canonical_name)
    if detail is None:
        raise HTTPException(status_code=404, detail="Library function not found.")
    return detail


def _library_service(library_db_path: str | None) -> LibraryFunctionService:
    return LibraryFunctionService(library_db_path)
