from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from backend.app.alignment.alignment_service import AlignmentService
from backend.app.alignment.fact_reader import AlignmentFactReader
from backend.app.alignment.review_service import AlignmentReviewService
from backend.app.alignment.schemas import (
    AlignmentDeploymentRequest,
    AlignmentReviewRequest,
    AlignmentRunCreateRequest,
)
from backend.app.alignment.verifier import ProviderAlignmentVerifier
from backend.app.llm.config import LLMSettings
from backend.app.llm.runtime import create_llm_runtime
from backend.app.persistence.alignment_store import AlignmentStore, AlignmentStoreError, alignment_run_model
from backend.app.persistence.retrieval_read_store import RetrievalReadError
from backend.app.services.alignment_run_coordinator import AlignmentRunCoordinator


router = APIRouter()
_coordinator: AlignmentRunCoordinator | None = None


@lru_cache(maxsize=1)
def get_alignment_store() -> AlignmentStore:
    return AlignmentStore(os.getenv("ALIGNMENT_DB_PATH", "data/paper_code_alignment.sqlite3"))


@lru_cache(maxsize=1)
def get_alignment_service() -> AlignmentService:
    from backend.app.retrieval.api import get_retrieval_service

    llm_runtime = create_llm_runtime(LLMSettings.from_env(text_llm_enabled=True))
    verifier = (
        ProviderAlignmentVerifier(llm_runtime.router)
        if llm_runtime.router.has_available_provider
        else None
    )
    return AlignmentService(
        store=get_alignment_store(),
        fact_reader=AlignmentFactReader(
            os.getenv("STRUCTURED_INDEX_DB_PATH", "data/structured_index.sqlite3")
        ),
        retrieval_service=get_retrieval_service(),
        verifier=verifier,
    )


async def start_alignment_runtime() -> None:
    global _coordinator
    if not _enabled() or _coordinator is not None:
        return
    coordinator = AlignmentRunCoordinator(
        store=get_alignment_store(),
        service=get_alignment_service(),
        max_concurrent_runs=int(os.getenv("ALIGNMENT_MAX_CONCURRENT_RUNS", "2")),
    )
    await coordinator.start()
    _coordinator = coordinator


async def stop_alignment_runtime() -> None:
    global _coordinator
    if _coordinator:
        await _coordinator.stop()
    _coordinator = None


@router.post("/repositories/{repo_id}/alignments/runs", status_code=202)
async def create_alignment_run(
    repo_id: str,
    payload: AlignmentRunCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        version = get_alignment_service().fact_reader.resolve_version(repo_id, payload.index_version_id)
        run, reused = get_alignment_service().prepare_run(
            repo_id=repo_id,
            index_version_id=version,
            paper_id=payload.paper_id,
            request=payload.model_copy(update={"index_version_id": version}).model_dump(mode="json"),
            caller_scope=_caller_scope(request),
            idempotency_key=idempotency_key,
            retry_of_run_id=payload.retry_of_run_id,
        )
        if _coordinator:
            _coordinator.notify()
        return {"run": alignment_run_model(run), "reused": reused}
    except (AlignmentStoreError, RetrievalReadError, ValueError) as exc:
        return _error(getattr(exc, "error_code", _value_error_code(exc)), str(exc), getattr(exc, "retryable", False))


@router.get("/alignments/runs/{run_id}")
def get_alignment_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        return alignment_run_model(get_alignment_store().get_run_for_caller(run_id, _caller_scope(request)))
    except AlignmentStoreError as exc:
        return _error(exc.error_code, str(exc), exc.retryable)


@router.post("/alignments/runs/{run_id}/cancel", status_code=202)
def cancel_alignment_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        get_alignment_store().get_run_for_caller(run_id, _caller_scope(request))
        run = get_alignment_store().request_cancel(run_id)
        if _coordinator:
            _coordinator.notify()
        return alignment_run_model(run)
    except AlignmentStoreError as exc:
        return _error(exc.error_code, str(exc), exc.retryable)


@router.get("/repositories/{repo_id}/alignments")
def list_alignments(
    repo_id: str,
    index_version_id: str,
    paper_id: str,
    request: Request,
    deployment_name: str = "default",
    model_profile_id: str | None = None,
    status: str | None = None,
    relation: str | None = None,
    profile_id: str | None = None,
    entity_id: str | None = None,
    source: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        if model_profile_id:
            run = get_alignment_store().find_active_run(
                repo_id=repo_id,
                index_version_id=index_version_id,
                paper_id=paper_id,
                model_profile_id=model_profile_id,
            )
            get_alignment_store().get_run_for_caller(run["run_id"], _caller_scope(request))
            decisions = _filter_decisions(
                run["run_id"], status, relation, profile_id, entity_id, source
            )
            return {
                "deployment": None,
                "model_profile_id": model_profile_id,
                "alignment_run_id": run["run_id"],
                "total": len(decisions),
                "limit": limit,
                "offset": offset,
                "decisions": decisions[offset : offset + limit],
            }
        deployment = get_alignment_store().get_deployment(repo_id, index_version_id, paper_id, deployment_name)
        get_alignment_store().get_run_for_caller(
            deployment.active_run_id, _caller_scope(request)
        )
        decisions = _filter_decisions(
            deployment.active_run_id, status, relation, profile_id, entity_id, source
        )
        return {
            "deployment": deployment,
            "model_profile_id": deployment.model_profile_id,
            "alignment_run_id": deployment.active_run_id,
            "total": len(decisions),
            "limit": limit,
            "offset": offset,
            "decisions": decisions[offset : offset + limit],
        }
    except AlignmentStoreError as exc:
        return _error(exc.error_code, str(exc), exc.retryable)


@router.get("/alignments/{decision_id}")
def get_alignment_decision(decision_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        detail = get_alignment_store().get_decision_detail(decision_id)
        get_alignment_store().get_run_for_caller(detail["run_id"], _caller_scope(request))
        effective = AlignmentReviewService(get_alignment_store()).effective_decision(decision_id)
        return {
            **detail,
            "effective": effective,
            "reviews": get_alignment_store().list_reviews(decision_id),
        }
    except AlignmentStoreError as exc:
        return _error(exc.error_code, str(exc), exc.retryable)


@router.post("/alignments/{decision_id}/reviews")
def review_alignment(decision_id: str, payload: AlignmentReviewRequest, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        row = get_alignment_store().get_decision_row(decision_id)
        get_alignment_store().get_run_for_caller(row["run_id"], _caller_scope(request))
        return AlignmentReviewService(get_alignment_store()).add_review(
            decision_id, payload, reviewer_scope=_caller_scope(request)
        )
    except AlignmentStoreError as exc:
        return _error(exc.error_code, str(exc), exc.retryable)


@router.get("/alignments/reviews/pending")
def pending_alignment_reviews(
    repo_id: str,
    index_version_id: str,
    paper_id: str,
    request: Request,
    deployment_name: str = "default",
):
    return list_alignments(
        repo_id,
        index_version_id,
        paper_id,
        request,
        deployment_name,
        model_profile_id=None,
        status="needs_review",
    )


@router.put("/repositories/{repo_id}/alignments/deployments/{deployment_name}")
def set_alignment_deployment(
    repo_id: str,
    deployment_name: str,
    payload: AlignmentDeploymentRequest,
    request: Request,
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        get_alignment_store().get_run_for_caller(
            payload.active_run_id, _caller_scope(request)
        )
        return get_alignment_store().set_deployment(
            deployment_name=deployment_name,
            repo_id=repo_id,
            index_version_id=payload.index_version_id,
            paper_id=payload.paper_id,
            model_profile_id=payload.model_profile_id,
            active_run_id=payload.active_run_id,
        )
    except AlignmentStoreError as exc:
        return _error(exc.error_code, str(exc), exc.retryable)


def _unavailable() -> JSONResponse | None:
    if _enabled():
        return None
    return _error("alignment_disabled", "Alignment is disabled.", False)


def _enabled() -> bool:
    return os.getenv("ALIGNMENT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _caller_scope(request: Request) -> str:
    return request.headers.get("X-Caller-Scope", "anonymous")


def _filter_decisions(
    run_id: str,
    status: str | None,
    relation: str | None,
    profile_id: str | None,
    entity_id: str | None,
    source: str | None,
):
    decisions = get_alignment_store().list_decisions(run_id, status)
    candidates = {item.candidate_id: item for item in get_alignment_store().load_candidates(run_id)}
    output = []
    for decision in decisions:
        if profile_id and decision.profile_id != profile_id:
            continue
        if relation and not any(item.relation_type == relation for item in decision.selections):
            continue
        if entity_id and not any(
            candidates.get(item.candidate_id)
            and candidates[item.candidate_id].code_entity_id == entity_id
            for item in decision.selections
        ):
            continue
        if source and decision.decision_source != source and not any(
            contribution.source == source
            for selection in decision.selections
            if selection.candidate_id in candidates
            for contribution in candidates[selection.candidate_id].source_contributions
        ):
            continue
        output.append(decision)
    return output


def _value_error_code(exc: Exception) -> str:
    value = str(exc)
    return value.split(":", 1)[0] if ":" in value else "alignment_invalid_request"


def _error(error_code: str, message: str, retryable: bool) -> JSONResponse:
    if error_code == "idempotency_key_conflict":
        status = 409
    elif error_code in {"alignment_disabled", "alignment_busy"}:
        status = 503
    elif error_code in {"review_conflict", "alignment_cancel_not_allowed"}:
        status = 409
    elif error_code in {"alignment_run_forbidden"}:
        status = 403
    elif error_code.endswith("not_found") or error_code in {"paper_not_found", "alignment_profile_required"}:
        status = 404
    else:
        status = 422
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "error_code": error_code,
                "component": "alignment",
                "message": message,
                "retryable": retryable,
                "context": {},
                "trace_id": None,
            }
        },
    )
