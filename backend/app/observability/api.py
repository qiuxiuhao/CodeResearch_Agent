from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.app.observability.schemas import CallerIdentity, ReplayManifest, TraceFilter, TraceRecord
from backend.app.persistence.observability_store import ObservabilityStoreError
from backend.app.services.observability_runtime import get_observability_runtime
from backend.app.observability.context import current_trace_context


router = APIRouter(prefix="/observability", tags=["observability"])
_SSE_SLOTS = BoundedSemaphore(20)


@router.get("/traces")
def list_traces(
    request: Request,
    start: datetime | None = None,
    end: datetime | None = None,
    status: str | None = None,
    trace_type: str | None = None,
    component: str | None = None,
    operation: str | None = None,
    repo_id: str | None = None,
    index_version_id: str | None = None,
    run_id: str | None = None,
    error_code: str | None = None,
    min_duration_ms: float | None = Query(default=None, ge=0),
    max_duration_ms: float | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int = Query(default=0, ge=0),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        filters = TraceFilter(
            start=start, end=end, status=status, trace_type=trace_type, component=component,
            operation=operation, repo_id=repo_id, index_version_id=index_version_id,
            run_id=run_id, error_code=error_code, min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
        )
        caller = _caller(request)
        runtime = get_observability_runtime()
        if not runtime.access_policy.can_list_traces(caller, filters):
            return _not_found()
        items = runtime.store.list_traces(filters, limit=limit, offset=cursor)
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "next_cursor": cursor + len(items) if len(items) == limit else None,
            "limit": limit,
        }
    except (ValueError, ObservabilityStoreError) as exc:
        return _error(getattr(exc, "error_code", "invalid_trace_filter"), retryable=False)


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, request: Request):
    result = _authorized_trace(trace_id, request)
    if isinstance(result, JSONResponse):
        return result
    runtime = get_observability_runtime()
    artifacts = runtime.store.list_artifacts(trace_id)
    return {
        "trace": result.model_dump(mode="json"),
        "links": [item.model_dump(mode="json") for item in runtime.store.list_links(trace_id)],
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
        "replay_manifest": _replay_manifest(result, artifacts).model_dump(mode="json"),
    }


@router.get("/traces/{trace_id}/spans")
def list_spans(
    trace_id: str, request: Request, limit: int = Query(default=200, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
):
    result = _authorized_trace(trace_id, request)
    if isinstance(result, JSONResponse):
        return result
    items = [
        item.model_dump(mode="json")
        for item in get_observability_runtime().store.list_spans(
            trace_id, limit=limit, offset=offset
        )
    ]
    bounded, truncated = _bounded_items(items)
    return {
        "items": bounded,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
        "next_offset": offset + len(bounded) if truncated or len(items) == limit else None,
    }


@router.get("/traces/{trace_id}/spans/{span_id}")
def get_span(trace_id: str, span_id: str, request: Request):
    result = _authorized_trace(trace_id, request)
    if isinstance(result, JSONResponse):
        return result
    try:
        return get_observability_runtime().store.get_span(trace_id, span_id)
    except ObservabilityStoreError:
        return _not_found()


@router.get("/traces/{trace_id}/events")
def list_events(
    trace_id: str, request: Request, after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
):
    result = _authorized_trace(trace_id, request)
    if isinstance(result, JSONResponse):
        return result
    items = [
        item.model_dump(mode="json")
        for item in get_observability_runtime().store.list_events(
            trace_id, after_sequence=after_sequence, limit=limit
        )
    ]
    bounded, truncated = _bounded_items(items)
    return {"items": bounded, "truncated": truncated}


@router.get("/traces/{trace_id}/events/stream")
async def stream_events(
    trace_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    result = _authorized_trace(trace_id, request)
    if isinstance(result, JSONResponse):
        return result
    try:
        cursor = int(last_event_id or "0")
        if cursor < 0:
            raise ValueError
    except ValueError:
        return _error("trace_cursor_expired", retryable=False, status=409)
    minimum, maximum = get_observability_runtime().store.event_sequence_bounds(trace_id)
    if cursor and (
        maximum is None or cursor > maximum or (minimum is not None and cursor < minimum - 1)
    ):
        return _error("trace_cursor_expired", retryable=False, status=409)
    if not _SSE_SLOTS.acquire(blocking=False):
        return _error("event_stream_limit", retryable=True, status=429)

    async def events():
        nonlocal cursor
        try:
            idle = 0
            while not await request.is_disconnected():
                items = await asyncio.to_thread(
                    get_observability_runtime().store.list_events,
                    trace_id,
                    after_sequence=cursor,
                    limit=200,
                )
                if items:
                    idle = 0
                    for item in items:
                        cursor = item.stream_sequence or cursor
                        payload = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                        yield f"id: {cursor}\nevent: trace\ndata: {payload}\n\n"
                    trace = await asyncio.to_thread(get_observability_runtime().store.get_trace, trace_id)
                    if trace.status != "running" and not await asyncio.to_thread(
                        get_observability_runtime().store.list_events,
                        trace_id,
                        after_sequence=cursor,
                        limit=1,
                    ):
                        return
                else:
                    idle += 1
                    trace = await asyncio.to_thread(
                        get_observability_runtime().store.get_trace, trace_id
                    )
                    if trace.status != "running":
                        return
                    if idle % 30 == 0:
                        yield ": heartbeat\n\n"
                    await asyncio.sleep(0.5)
        finally:
            _SSE_SLOTS.release()

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/metrics/summary")
def metrics_summary(request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    caller = _caller(request)
    runtime = get_observability_runtime()
    if caller.identity_type != "local_admin":
        return _not_found()
    return {
        "store": runtime.store.metrics_summary(),
        "runtime": runtime.metrics.snapshot(),
        "store_failure_count": getattr(runtime.recorder, "store_failure_count", 0),
    }


@router.get("/metrics/timeseries")
def metrics_timeseries(
    request: Request,
    start: datetime | None = None,
    end: datetime | None = None,
    bucket_seconds: int = Query(default=60, ge=1, le=86_400),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if _caller(request).identity_type != "local_admin":
        return _not_found()
    window_end = end or datetime.now(UTC)
    window_start = start or (window_end - timedelta(hours=1))
    if window_start.tzinfo is None or window_end.tzinfo is None:
        return _error("invalid_trace_filter", retryable=False)
    if window_end <= window_start or window_end - window_start > timedelta(days=31):
        return _error("metrics_range_too_large", retryable=False)
    if (window_end - window_start).total_seconds() / bucket_seconds > 2_000:
        return _error("metrics_range_too_large", retryable=False)
    points = get_observability_runtime().store.metrics_timeseries(
        window_start.astimezone(UTC), window_end.astimezone(UTC),
        bucket_seconds=bucket_seconds,
    )
    return {
        "points": points,
        "telemetry_complete": all(bool(item["telemetry_complete"]) for item in points),
    }


def _authorized_trace(trace_id: str, request: Request) -> TraceRecord | JSONResponse:
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    runtime = get_observability_runtime()
    try:
        trace = runtime.store.get_trace(trace_id)
    except ObservabilityStoreError:
        return _not_found()
    if not runtime.access_policy.can_read_trace(_caller(request), trace):
        return _not_found()
    return trace


def _caller(request: Request) -> CallerIdentity:
    host = request.client.host if request.client else "unknown"
    if host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return CallerIdentity(identity_type="local_admin", subject="local-admin")
    return CallerIdentity(identity_type="anonymous", subject="anonymous")


def _unavailable() -> JSONResponse | None:
    runtime = get_observability_runtime()
    if not runtime.api_enabled:
        return _error("observability_api_disabled", retryable=False, status=503)
    if not runtime.enabled:
        return _error("observability_disabled", retryable=False, status=503)
    return None


def _not_found() -> JSONResponse:
    return _error("trace_not_found", retryable=False, status=404)


def _error(error_code: str, *, retryable: bool, status: int = 400) -> JSONResponse:
    context = current_trace_context()
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "error_code": error_code,
                "component": "observability",
                "message": error_code.replace("_", " "),
                "retryable": retryable,
                "context": {},
                "trace_id": context.trace_id if context else None,
            }
        },
    )


def _bounded_items(items: list[dict], max_bytes: int = 2 * 1024 * 1024) -> tuple[list[dict], bool]:
    output: list[dict] = []
    used = 32
    for item in items:
        size = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if used + size > max_bytes:
            return output, True
        output.append(item)
        used += size
    return output, False


def _replay_manifest(trace: TraceRecord, artifacts) -> ReplayManifest:
    reasons: list[str] = []
    if not trace.run_id:
        reasons.append("run_id_missing")
    if not trace.repo_id or not trace.index_version_id:
        reasons.append("repository_version_missing")
    if not any(item.artifact_type == "checkpoint" for item in artifacts):
        reasons.append("checkpoint_not_linked")
    # v1.8 never verifies or executes a replay. Readiness remains conservative until all
    # referenced business artifacts are checked by their owning stores.
    reasons.append("business_artifact_availability_not_verified")
    return ReplayManifest(
        trace_id=trace.trace_id,
        run_id=trace.run_id,
        repo_id=trace.repo_id,
        index_version_id=trace.index_version_id,
        graph_version=_string_attribute(trace, "cra.graph.version"),
        model_profile_id=(
            _string_attribute(trace, "cra.model.profile")
            or _string_attribute(trace, "cra.scorer.profile")
        ),
        artifact_ref_ids=[item.ref_id for item in artifacts],
        readiness="not_ready" if reasons else "replay_ready",
        reason_codes=reasons,
        generated_at=datetime.now(UTC),
    )


def _string_attribute(trace: TraceRecord, key: str) -> str | None:
    value = trace.attributes.get(key)
    return value if isinstance(value, str) else None
