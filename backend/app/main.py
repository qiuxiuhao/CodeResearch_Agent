from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from backend.app.services.analysis_service import run_analysis, summarize_state


app = FastAPI(title="CodeResearch Agent", version="0.2.1")


class AnalysisTaskRequest(BaseModel):
    zip_path: str
    output_root: str = "outputs"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analysis/tasks")
def create_analysis_task(request: AnalysisTaskRequest) -> dict:
    state = run_analysis(request.zip_path, request.output_root)
    return summarize_state(state)
