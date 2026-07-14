from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
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
from backend.app.llm.config import LLMSettings
from backend.app.vision.config import VisionSettings
from backend.app.config.pdf_safety import PDFSafetySettings, zip_max_file_bytes


app = FastAPI(title="CodeResearch Agent", version="1.2.3")
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
    analysis_mode: Literal["rule", "hybrid"] | None = None
    external_model_consent: bool = False
    text_llm_enabled: bool | None = None
    vision_vlm_enabled: bool | None = None
    external_text_consent: bool | None = None
    external_vision_consent: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/analysis/tasks")
def list_analysis_tasks(output_root: str = "outputs") -> dict:
    return {"tasks": list_task_summaries(output_root)}


@app.post("/analysis/tasks")
def create_analysis_task(request: AnalysisTaskRequest) -> dict:
    try:
        state = _run_analysis_with_llm_options(
            request.zip_path, request.output_root, request.library_db_path, request.paper_pdf_path,
            request.analysis_mode, request.external_model_consent,
            request.text_llm_enabled, request.vision_vlm_enabled,
            request.external_text_consent, request.external_vision_consent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return summarize_state(state)


@app.post("/analysis/tasks/upload")
async def create_analysis_task_from_upload(
    zip_file: UploadFile = File(...),
    paper_pdf: UploadFile | None = File(None),
    output_root: str = Form("outputs"),
    library_db_path: str | None = Form(None),
    analysis_mode: Literal["rule", "hybrid"] | None = Form(None),
    external_model_consent: bool = Form(False),
    text_llm_enabled: bool | None = Form(None),
    vision_vlm_enabled: bool | None = Form(None),
    external_text_consent: bool | None = Form(None),
    external_vision_consent: bool = Form(False),
) -> dict:
    if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip_file must be a .zip file.")
    if paper_pdf and paper_pdf.filename and not paper_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="paper_pdf must be a .pdf file.")
    _validate_external_ai_consents(
        analysis_mode, external_model_consent, text_llm_enabled, vision_vlm_enabled,
        external_text_consent, external_vision_consent,
    )

    upload_dir = Path(output_root) / "_uploads" / uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / Path(zip_file.filename).name
    await _save_upload_limited(zip_file, zip_path, zip_max_file_bytes(), "ZIP")

    paper_pdf_path: Path | None = None
    if paper_pdf and paper_pdf.filename:
        paper_pdf_path = upload_dir / Path(paper_pdf.filename).name
        await _save_upload_limited(
            paper_pdf, paper_pdf_path, PDFSafetySettings.from_env().max_file_bytes, "PDF"
        )

    state = _run_analysis_with_llm_options(
        zip_path, output_root, library_db_path, paper_pdf_path, analysis_mode, external_model_consent,
        text_llm_enabled, vision_vlm_enabled, external_text_consent, external_vision_consent,
    )
    return summarize_state(state)


@app.get("/llm/public-config")
def get_llm_public_config() -> dict:
    return {**LLMSettings.from_env().public_config(), "vision": VisionSettings.from_env().public_config()}


@app.get("/vision/public-config")
def get_vision_public_config() -> dict:
    return VisionSettings.from_env().public_config()


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


@app.get("/analysis/tasks/{task_id}/figures/{figure_id}/preview")
def get_figure_preview(task_id: str, figure_id: str, output_root: str = "outputs"):
    result = load_task_result(task_id, output_root)
    figures = result.get("paper_figure_analysis", {}).get("figures", [])
    figure = next((item for item in figures if item.get("figure_id") == figure_id), None)
    preview_path = (figure or {}).get("canonical_preview", {}).get("path")
    if not preview_path:
        raise HTTPException(status_code=404, detail="Figure preview not found.")
    root = (Path(output_root) / task_id).resolve()
    candidate = Path(preview_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Figure preview not found.")
    return FileResponse(candidate, media_type="image/png")


@app.get("/analysis/tasks/{task_id}/figures/{figure_id}/assets/{asset_id}")
def get_figure_original_asset(task_id: str, figure_id: str, asset_id: str, output_root: str = "outputs"):
    result = load_task_result(task_id, output_root)
    figures = result.get("paper_figure_analysis", {}).get("figures", [])
    figure = next((item for item in figures if item.get("figure_id") == figure_id), None)
    asset = next((item for item in (figure or {}).get("original_assets", []) if item.get("asset_id") == asset_id), None)
    asset_path = (asset or {}).get("path")
    if not asset_path:
        raise HTTPException(status_code=404, detail="Figure original asset not found.")
    root = (Path(output_root) / task_id).resolve()
    candidate = Path(asset_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Figure original asset not found.")
    return FileResponse(candidate, media_type=asset.get("mime_type") or "application/octet-stream")


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


def _validate_external_model_consent(analysis_mode: str | None, consent: bool) -> None:
    _validate_external_ai_consents(analysis_mode, consent, None, False, None, False)


def _validate_external_ai_consents(
    analysis_mode: str | None, legacy_consent: bool, text_enabled: bool | None,
    vision_enabled: bool | None, text_consent: bool | None, vision_consent: bool,
) -> None:
    resolved_text_consent = legacy_consent if text_consent is None else text_consent
    if LLMSettings.from_env(analysis_mode, text_enabled).text_llm_enabled and not resolved_text_consent:
        raise HTTPException(
            status_code=400,
            detail="text_llm_enabled=true requires external_text_consent=true (legacy external_model_consent=true).",
        )
    if VisionSettings.from_env(vision_enabled).enabled and not vision_consent:
        raise HTTPException(status_code=400, detail="vision_vlm_enabled=true requires external_vision_consent=true.")


def _run_analysis_with_llm_options(
    zip_path, output_root, library_db_path, paper_pdf_path, analysis_mode: str | None, consent: bool,
    text_enabled: bool | None = None, vision_enabled: bool | None = None,
    text_consent: bool | None = None, vision_consent: bool = False,
):
    _validate_external_ai_consents(
        analysis_mode, consent, text_enabled, vision_enabled, text_consent, vision_consent,
    )
    if analysis_mode is None and not consent and text_enabled is None and vision_enabled is None and text_consent is None and not vision_consent:
        return run_analysis(zip_path, output_root, library_db_path, paper_pdf_path)
    return run_analysis(
        zip_path, output_root, library_db_path, paper_pdf_path,
        analysis_mode=analysis_mode, external_model_consent=consent,
        text_llm_enabled=text_enabled, vision_vlm_enabled=vision_enabled,
        external_text_consent=text_consent, external_vision_consent=vision_consent,
    )


async def _save_upload_limited(
    upload: UploadFile,
    destination: Path,
    max_bytes: int,
    label: str,
    chunk_size: int = 1024 * 1024,
) -> None:
    received = 0
    try:
        with destination.open("wb") as stream:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{label} upload exceeds the configured byte limit.",
                    )
                stream.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
