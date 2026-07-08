from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from backend.app.services.analysis_service import run_analysis, summarize_state


app = FastAPI(title="CodeResearch Agent", version="0.6.1")


class AnalysisTaskRequest(BaseModel):
    zip_path: str
    output_root: str = "outputs"
    library_db_path: str | None = None
    paper_pdf_path: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analysis/tasks")
def create_analysis_task(request: AnalysisTaskRequest) -> dict:
    state = run_analysis(request.zip_path, request.output_root, request.library_db_path, request.paper_pdf_path)
    return summarize_state(state)
