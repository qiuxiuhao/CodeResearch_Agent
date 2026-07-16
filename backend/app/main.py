from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.services.analysis_service import (
    list_task_summaries,
    load_task_report,
    load_task_result,
    run_analysis,
    summarize_state,
)
from backend.app.services.analysis_options import AnalysisOptionsError, resolve_analysis_options
from backend.app.agents.graph import ANALYSIS_GRAPH_STEPS, ProgressCallback
from backend.app.services.library_function_service import LibraryFunctionService
from backend.app.services.task_progress import new_task_id, progress_store
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.llm.config import LLMSettings
from backend.app.vision.config import VisionSettings
from backend.app.config.pdf_safety import PDFSafetySettings, zip_max_file_bytes
from backend.app.schemas.provider_settings import (
    ProviderApiKeyDeleteRequest,
    ProviderSettingsUpdateRequest,
    ProviderTestRequest,
    ProviderValidateRequest,
)
from backend.app.settings.provider_settings import ProviderSettingsService
from backend.app.settings.secret_store import SecretStoreConflictError, SecretStoreError
from backend.app.settings.security import require_settings_write_access


_analysis_executor: ThreadPoolExecutor | None = None


def _get_analysis_executor() -> ThreadPoolExecutor:
    global _analysis_executor
    if _analysis_executor is None or getattr(_analysis_executor, "_shutdown", False):
        _analysis_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis-task")
    return _analysis_executor


def _shutdown_analysis_executor() -> None:
    global _analysis_executor
    if _analysis_executor is not None:
        _analysis_executor.shutdown(wait=False, cancel_futures=True)
        _analysis_executor = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        _shutdown_analysis_executor()


app = FastAPI(title="CodeResearch Agent", version="1.3.4", lifespan=lifespan)
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
    analysis_mode: Literal["rule", "hybrid"] | None = Field(default=None, deprecated=True)
    external_model_consent: bool = Field(default=False, deprecated=True)
    text_llm_enabled: bool | None = None
    teaching_narrative_llm_enabled: bool | None = None
    vision_vlm_enabled: bool | None = None
    external_text_consent: bool | None = None
    external_vision_consent: bool = False
    teaching_diagrams_enabled: bool = True
    image_generation_enabled: bool | None = None
    external_image_consent: bool = False
    teaching_review_vlm_enabled: bool | None = None
    external_teaching_review_consent: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/analysis/tasks")
def list_analysis_tasks(output_root: str = "outputs") -> dict:
    return {"tasks": list_task_summaries(output_root)}


@app.post("/analysis/tasks", deprecated=True)
def create_analysis_task(request: AnalysisTaskRequest) -> dict:
    analysis_mode, legacy_consent = _legacy_task_options(request)
    try:
        state = _run_analysis_with_llm_options(
            request.zip_path, request.output_root, request.library_db_path, request.paper_pdf_path,
            analysis_mode, legacy_consent,
            request.text_llm_enabled, request.teaching_narrative_llm_enabled, request.vision_vlm_enabled,
            request.external_text_consent, request.external_vision_consent,
            request.teaching_diagrams_enabled, request.image_generation_enabled,
            request.external_image_consent, request.teaching_review_vlm_enabled,
            request.external_teaching_review_consent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return summarize_state(state)


@app.post("/analysis/tasks/async")
def create_analysis_task_async(request: AnalysisTaskRequest) -> dict:
    analysis_mode, legacy_consent = _legacy_task_options(request)
    _validate_external_ai_consents(
        analysis_mode, legacy_consent, request.text_llm_enabled, request.vision_vlm_enabled,
        request.external_text_consent, request.external_vision_consent, request.image_generation_enabled,
        request.external_image_consent, request.teaching_review_vlm_enabled,
        request.teaching_narrative_llm_enabled, request.external_teaching_review_consent,
    )
    task_id = new_task_id()
    progress = progress_store.create(task_id=task_id, output_root=request.output_root)
    _get_analysis_executor().submit(
        _run_background_analysis,
        task_id,
        request.zip_path,
        request.output_root,
        request.library_db_path,
        request.paper_pdf_path,
        analysis_mode,
        legacy_consent,
        request.text_llm_enabled,
        request.teaching_narrative_llm_enabled,
        request.vision_vlm_enabled,
        request.external_text_consent,
        request.external_vision_consent,
        request.teaching_diagrams_enabled,
        request.image_generation_enabled,
        request.external_image_consent,
        request.teaching_review_vlm_enabled,
        request.external_teaching_review_consent,
    )
    return progress


@app.post("/analysis/tasks/upload", deprecated=True)
async def create_analysis_task_from_upload(
    zip_file: UploadFile = File(...),
    paper_pdf: UploadFile | None = File(None),
    output_root: str = Form("outputs"),
    library_db_path: str | None = Form(None),
    analysis_mode: Literal["rule", "hybrid"] | None = Form(None, deprecated=True),
    external_model_consent: bool = Form(False, deprecated=True),
    text_llm_enabled: bool | None = Form(None),
    teaching_narrative_llm_enabled: bool | None = Form(None),
    vision_vlm_enabled: bool | None = Form(None),
    external_text_consent: bool | None = Form(None),
    external_vision_consent: bool = Form(False),
    teaching_diagrams_enabled: bool = Form(True),
    image_generation_enabled: bool | None = Form(None),
    external_image_consent: bool = Form(False),
    teaching_review_vlm_enabled: bool | None = Form(None),
    external_teaching_review_consent: bool = Form(False),
) -> dict:
    if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip_file must be a .zip file.")
    if paper_pdf and paper_pdf.filename and not paper_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="paper_pdf must be a .pdf file.")
    _validate_external_ai_consents(
        analysis_mode, external_model_consent, text_llm_enabled, vision_vlm_enabled,
        external_text_consent, external_vision_consent, image_generation_enabled,
        external_image_consent, teaching_review_vlm_enabled,
        teaching_narrative_llm_enabled, external_teaching_review_consent,
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
        text_llm_enabled, teaching_narrative_llm_enabled, vision_vlm_enabled,
        external_text_consent, external_vision_consent,
        teaching_diagrams_enabled, image_generation_enabled, external_image_consent, teaching_review_vlm_enabled,
        external_teaching_review_consent,
    )
    return summarize_state(state)


@app.post("/analysis/tasks/upload/async")
async def create_analysis_task_from_upload_async(
    zip_file: UploadFile = File(...),
    paper_pdf: UploadFile | None = File(None),
    output_root: str = Form("outputs"),
    library_db_path: str | None = Form(None),
    analysis_mode: Literal["rule", "hybrid"] | None = Form(None, deprecated=True),
    external_model_consent: bool = Form(False, deprecated=True),
    text_llm_enabled: bool | None = Form(None),
    teaching_narrative_llm_enabled: bool | None = Form(None),
    vision_vlm_enabled: bool | None = Form(None),
    external_text_consent: bool | None = Form(None),
    external_vision_consent: bool = Form(False),
    teaching_diagrams_enabled: bool = Form(True),
    image_generation_enabled: bool | None = Form(None),
    external_image_consent: bool = Form(False),
    teaching_review_vlm_enabled: bool | None = Form(None),
    external_teaching_review_consent: bool = Form(False),
) -> dict:
    if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip_file must be a .zip file.")
    if paper_pdf and paper_pdf.filename and not paper_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="paper_pdf must be a .pdf file.")
    _validate_external_ai_consents(
        analysis_mode, external_model_consent, text_llm_enabled, vision_vlm_enabled,
        external_text_consent, external_vision_consent, image_generation_enabled,
        external_image_consent, teaching_review_vlm_enabled,
        teaching_narrative_llm_enabled, external_teaching_review_consent,
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

    task_id = new_task_id()
    progress = progress_store.create(task_id=task_id, output_root=output_root)
    _get_analysis_executor().submit(
        _run_background_analysis,
        task_id,
        zip_path,
        output_root,
        library_db_path,
        paper_pdf_path,
        analysis_mode,
        external_model_consent,
        text_llm_enabled,
        teaching_narrative_llm_enabled,
        vision_vlm_enabled,
        external_text_consent,
        external_vision_consent,
        teaching_diagrams_enabled,
        image_generation_enabled,
        external_image_consent,
        teaching_review_vlm_enabled,
        external_teaching_review_consent,
    )
    return progress


@app.get("/llm/public-config")
def get_llm_public_config() -> dict:
    return {
        **LLMSettings.from_env().public_config(),
        "vision": VisionSettings.from_env().public_config(),
        "image_generation": ImageGenerationSettings.from_env().public_config(),
    }


@app.get("/vision/public-config")
def get_vision_public_config() -> dict:
    return VisionSettings.from_env().public_config()


@app.get("/image-generation/public-config")
def get_image_generation_public_config() -> dict:
    return ImageGenerationSettings.from_env().public_config()


@app.get("/settings/providers")
def get_provider_settings() -> dict:
    return ProviderSettingsService().list_public_settings().model_dump(mode="json")


@app.put("/settings/providers/{provider_id}")
def put_provider_settings(provider_id: str, payload: ProviderSettingsUpdateRequest, request: Request) -> dict:
    require_settings_write_access(request)
    try:
        return ProviderSettingsService().save(provider_id, payload).model_dump(mode="json")
    except SecretStoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SecretStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/settings/providers/{provider_id}/api-key")
def delete_provider_api_key(provider_id: str, payload: ProviderApiKeyDeleteRequest, request: Request) -> dict:
    require_settings_write_access(request)
    try:
        return ProviderSettingsService().delete_api_key(provider_id, payload).model_dump(mode="json")
    except SecretStoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SecretStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/settings/providers/{provider_id}/validate")
def validate_provider_settings(provider_id: str, payload: ProviderValidateRequest, request: Request) -> dict:
    require_settings_write_access(request)
    try:
        return ProviderSettingsService().validate(provider_id, payload, require_configured_key=True).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/settings/providers/{provider_id}/test")
def test_provider_settings(provider_id: str, payload: ProviderTestRequest, request: Request) -> dict:
    require_settings_write_access(request)
    try:
        return ProviderSettingsService().test_provider(provider_id, confirm_cost=payload.confirm_cost).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/analysis/tasks/{task_id}")
def get_analysis_task_result(task_id: str, output_root: str = "outputs") -> dict:
    try:
        return load_task_result(task_id, output_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/analysis/tasks/{task_id}/progress")
def get_analysis_task_progress(task_id: str, output_root: str = "outputs") -> dict:
    try:
        return progress_store.get(task_id)
    except KeyError:
        task_dir = Path(output_root) / task_id
        if task_dir.is_dir() and (task_dir / "report.md").is_file():
            summary = load_task_result(task_id, output_root).get("summary", {})
            return {
                "task_id": task_id,
                "status": "completed",
                "current_node": None,
                "current_label": "分析完成",
                "completed_nodes": len(ANALYSIS_GRAPH_STEPS),
                "total_nodes": len(ANALYSIS_GRAPH_STEPS),
                "percent": 100,
                "error": None,
                "summary": summary,
                "steps": [{**step, "status": "done"} for step in ANALYSIS_GRAPH_STEPS],
                "created_at": None,
                "started_at": None,
                "updated_at": None,
                "finished_at": None,
            }
        raise HTTPException(status_code=404, detail="Task progress not found.")


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


@app.get("/analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/{asset_name}")
def get_teaching_diagram_asset(task_id: str, diagram_id: str, asset_name: str, output_root: str = "outputs"):
    if asset_name not in {"blueprint.svg", "blueprint.png", "final.png", "raw.png"}:
        raise HTTPException(status_code=404, detail="Teaching diagram asset not found.")
    result = load_task_result(task_id, output_root)
    diagrams = result.get("teaching_diagrams", {}).get("diagrams", [])
    item = next((diagram for diagram in diagrams if diagram.get("diagram_id") == diagram_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Teaching diagram not found.")
    asset_key = {
        "blueprint.svg": "blueprint_svg",
        "blueprint.png": "blueprint_png",
        "final.png": "final_asset",
        "raw.png": "generated_raw",
    }[asset_name]
    asset = item.get(asset_key) or {}
    path_value = asset.get("path")
    if not path_value:
        raise HTTPException(status_code=404, detail="Teaching diagram asset not found.")
    root = (Path(output_root) / task_id).resolve()
    path = Path(path_value)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Teaching diagram asset not found.")
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


def _legacy_task_options(request: AnalysisTaskRequest) -> tuple[str | None, bool]:
    payload = request.model_dump(include={"analysis_mode", "external_model_consent"})
    return payload.get("analysis_mode"), bool(payload.get("external_model_consent", False))


def _validate_external_ai_consents(
    analysis_mode: str | None, legacy_consent: bool, text_enabled: bool | None,
    vision_enabled: bool | None, text_consent: bool | None, vision_consent: bool,
    image_enabled: bool | None = None, image_consent: bool = False,
    teaching_review_enabled: bool | None = None,
    teaching_narrative_enabled: bool | None = None,
    teaching_review_consent: bool = False,
) -> None:
    try:
        resolve_analysis_options(
            analysis_mode=analysis_mode,
            external_model_consent=legacy_consent,
            text_llm_enabled=text_enabled,
            teaching_narrative_llm_enabled=teaching_narrative_enabled,
            vision_vlm_enabled=vision_enabled,
            external_text_consent=text_consent,
            external_vision_consent=vision_consent,
            image_generation_enabled=image_enabled,
            external_image_consent=image_consent,
            teaching_review_vlm_enabled=teaching_review_enabled,
            external_teaching_review_consent=teaching_review_consent,
        )
    except AnalysisOptionsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _run_analysis_with_llm_options(
    zip_path, output_root, library_db_path, paper_pdf_path, analysis_mode: str | None, consent: bool,
    text_enabled: bool | None = None, teaching_narrative_enabled: bool | None = None,
    vision_enabled: bool | None = None,
    text_consent: bool | None = None, vision_consent: bool = False,
    teaching_diagrams_enabled: bool = True, image_enabled: bool | None = None,
    image_consent: bool = False, teaching_review_enabled: bool | None = None,
    teaching_review_consent: bool = False,
    task_id: str | None = None,
    progress_callback: ProgressCallback | None = None,
):
    _validate_external_ai_consents(
        analysis_mode, consent, text_enabled, vision_enabled, text_consent, vision_consent,
        image_enabled, image_consent, teaching_review_enabled,
        teaching_narrative_enabled, teaching_review_consent,
    )
    if (
        analysis_mode is None and not consent and text_enabled is None and vision_enabled is None
        and text_consent is None and not vision_consent and teaching_diagrams_enabled
        and teaching_narrative_enabled is None
        and image_enabled is None and not image_consent and teaching_review_enabled is None
        and not teaching_review_consent and task_id is None and progress_callback is None
    ):
        return run_analysis(zip_path, output_root, library_db_path, paper_pdf_path)
    return run_analysis(
        zip_path, output_root, library_db_path, paper_pdf_path,
        analysis_mode=analysis_mode, external_model_consent=consent,
        text_llm_enabled=text_enabled, vision_vlm_enabled=vision_enabled,
        teaching_narrative_llm_enabled=teaching_narrative_enabled,
        external_text_consent=text_consent, external_vision_consent=vision_consent,
        teaching_diagrams_enabled=teaching_diagrams_enabled,
        image_generation_enabled=image_enabled,
        external_image_consent=image_consent,
        teaching_review_vlm_enabled=teaching_review_enabled,
        external_teaching_review_consent=teaching_review_consent,
        task_id=task_id,
        progress_callback=progress_callback,
    )


def _run_background_analysis(
    task_id: str,
    zip_path,
    output_root,
    library_db_path,
    paper_pdf_path,
    analysis_mode: str | None,
    consent: bool,
    text_enabled: bool | None,
    teaching_narrative_enabled: bool | None,
    vision_enabled: bool | None,
    text_consent: bool | None,
    vision_consent: bool,
    teaching_diagrams_enabled: bool,
    image_enabled: bool | None,
    image_consent: bool,
    teaching_review_enabled: bool | None,
    teaching_review_consent: bool,
) -> None:
    progress_store.mark_running(task_id)
    try:
        state = _run_analysis_with_llm_options(
            zip_path, output_root, library_db_path, paper_pdf_path, analysis_mode, consent,
            text_enabled, teaching_narrative_enabled, vision_enabled,
            text_consent, vision_consent, teaching_diagrams_enabled,
            image_enabled, image_consent, teaching_review_enabled, teaching_review_consent,
            task_id=task_id,
            progress_callback=_progress_callback_for(task_id),
        )
        progress_store.complete(task_id, summarize_state(state))
    except Exception as exc:
        progress_store.fail(task_id, str(exc))


def _progress_callback_for(task_id: str) -> ProgressCallback:
    def callback(
        event: str,
        node_id: str,
        label: str,
        index: int,
        total: int,
        state,
        exc: BaseException | None,
    ) -> None:
        progress_store.update_node(task_id, event, node_id, label, index, total, state, exc)

    return callback


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
