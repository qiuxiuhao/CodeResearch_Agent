from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from backend.app.agents.research.runtime import build_research_graph_factory
from backend.app.agents.research.schemas import (
    ResearchRunAccepted,
    ResearchRunCreateRequest,
    ResearchRunResumeRequest,
    ResearchRunView,
)
from backend.app.persistence.research_checkpoint import ResearchCheckpointError, ResearchCheckpointRuntime
from backend.app.persistence.research_run_store import ResearchRunStore, ResearchRunStoreError
from backend.app.persistence.retrieval_read_store import RetrievalReadError
from backend.app.retrieval.api import get_retrieval_service
from backend.app.services.research_run_coordinator import ResearchRunCoordinator
from backend.app.agents.research.tool_registry import shutdown_sync_tool_executor
from backend.app.observability.context import current_trace_context
from backend.app.services.observability_runtime import get_observability_runtime


router = APIRouter()
_coordinator: ResearchRunCoordinator | None = None
_startup_error: ResearchCheckpointError | None = None


async def start_research_agent_runtime() -> None:
    global _coordinator, _startup_error
    if not _enabled() or _coordinator is not None:
        return
    run_store = ResearchRunStore(os.getenv("RESEARCH_RUN_DB_PATH", "data/research_runs.sqlite3"))
    checkpoint = ResearchCheckpointRuntime(
        os.getenv("RESEARCH_CHECKPOINT_DB_PATH", "data/research_checkpoints.sqlite3")
    )
    retrieval = get_retrieval_service()
    read_store = retrieval.read_store
    coordinator = ResearchRunCoordinator(
        run_store=run_store,
        checkpoint_runtime=checkpoint,
        graph_factory=build_research_graph_factory(
            retrieval_service=retrieval, read_store=read_store, run_store=run_store
        ),
        max_concurrent_runs=int(os.getenv("RESEARCH_AGENT_MAX_CONCURRENT_RUNS", "2")),
    )
    try:
        await coordinator.start()
    except ResearchCheckpointError as exc:
        _startup_error = exc
        return
    _coordinator = coordinator
    _startup_error = None


async def stop_research_agent_runtime() -> None:
    global _coordinator
    if _coordinator is not None:
        await _coordinator.stop()
    _coordinator = None
    shutdown_sync_tool_executor()


@router.post("/repositories/{repo_id}/research/agent/runs", status_code=202)
async def create_agent_run(
    repo_id: str,
    payload: ResearchRunCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        version_id = get_retrieval_service().read_store.resolve_version(
            repo_id, payload.index_version_id
        )
        run, reused = _coordinator.run_store.create_run(
            repo_id=repo_id,
            index_version_id=version_id,
            request=payload.model_copy(update={"index_version_id": version_id}),
            caller_scope=_caller_scope(request),
            idempotency_key=idempotency_key,
        )
        context = current_trace_context()
        if context is not None and not reused:
            get_observability_runtime().register_enqueue_link(
                run["run_id"], context.trace_id, context.span_id
            )
        _coordinator.notify()
        return ResearchRunAccepted(
            run_id=run["run_id"], thread_id=run["thread_id"], status=run["status"],
            repo_id=run["repo_id"], index_version_id=run["index_version_id"],
            created_at=run["created_at"],
        )
    except (ResearchRunStoreError, RetrievalReadError) as exc:
        return _error(exc.error_code, str(exc), retryable=getattr(exc, "retryable", False))


@router.get("/research/agent/runs/{run_id}")
async def get_agent_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        return _run_view(
            _coordinator.run_store.get_run_for_caller(run_id, _caller_scope(request))
        )
    except ResearchRunStoreError as exc:
        return _error(exc.error_code, str(exc), retryable=exc.retryable)


@router.post("/research/agent/runs/{run_id}/resume", status_code=202)
async def resume_agent_run(run_id: str, _payload: ResearchRunResumeRequest, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        _coordinator.run_store.get_run_for_caller(run_id, _caller_scope(request))
        context = current_trace_context()
        if context is not None:
            get_observability_runtime().register_enqueue_link(
                run_id, context.trace_id, context.span_id
            )
        run = await _coordinator.resume(run_id)
        return _run_view(run)
    except ResearchRunStoreError as exc:
        return _error(exc.error_code, str(exc), retryable=exc.retryable)


@router.post("/research/agent/runs/{run_id}/cancel", status_code=202)
async def cancel_agent_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        _coordinator.run_store.get_run_for_caller(run_id, _caller_scope(request))
        run = _coordinator.run_store.request_cancel(run_id)
        _coordinator.notify()
        return _run_view(run)
    except ResearchRunStoreError as exc:
        return _error(exc.error_code, str(exc), retryable=exc.retryable)


def _run_view(run: dict) -> ResearchRunView:
    result = run.get("result") or {}
    return ResearchRunView(
        run_id=run["run_id"], thread_id=run["thread_id"], repo_id=run["repo_id"],
        index_version_id=run["index_version_id"], status=run["status"], route=run.get("route"),
        current_plan_id=run.get("current_plan_id"), current_plan_version=run.get("current_plan_version"),
        current_step=result.get("current_step"), observations=result.get("observations", []),
        evidence_ids=result.get("evidence_ids", []), budget=run.get("budget") or {},
        answer=result.get("answer"), stop_reason=run.get("stop_reason"),
        retryable=run.get("retryable", False), cancel_requested=run.get("cancel_requested", False),
        resume_count=run.get("resume_count", 0), created_at=run["created_at"],
        started_at=run.get("started_at"), updated_at=run["updated_at"],
        finished_at=run.get("finished_at"), warnings=result.get("warnings", []),
    )


def _unavailable() -> JSONResponse | None:
    if not _enabled():
        return _error(
            "research_agent_disabled",
            "Research Agent is disabled. Set RESEARCH_AGENT_ENABLED=true to enable it.",
            retryable=False,
        )
    if _startup_error is not None:
        return _error(_startup_error.error_code, str(_startup_error), retryable=False)
    if _coordinator is None:
        return _error("research_agent_unavailable", "Research Agent runtime is not ready.", retryable=True)
    return None


def _error(error_code: str, message: str, *, retryable: bool) -> JSONResponse:
    context = current_trace_context()
    status = 409 if error_code == "idempotency_key_conflict" else 404
    if error_code in {
        "research_agent_disabled", "research_agent_unavailable", "checkpoint_dependency_missing",
        "checkpoint_version_unsafe", "checkpoint_serializer_unsupported",
    }:
        status = 503
    if error_code in {"resume_not_allowed", "invalid_run_transition", "run_version_incompatible"}:
        status = 409
    if error_code == "agent_run_forbidden":
        status = 403
    return JSONResponse(status_code=status, content={"error": {
        "error_code": error_code, "component": "research_agent", "message": message,
        "retryable": retryable, "context": {},
        "trace_id": context.trace_id if context else None,
    }})


def _caller_scope(request: Request) -> str:
    explicit = request.headers.get("X-Caller-Scope")
    if explicit:
        return explicit[:500]
    host = request.client.host if request.client else "local"
    return f"anonymous:{host}"


def _enabled() -> bool:
    return os.getenv("RESEARCH_AGENT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
