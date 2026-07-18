from __future__ import annotations

import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.app.observability.context import start_span_or_root
from backend.app.services.observability_runtime import get_observability_runtime


_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_TRACESTATE = re.compile(r"^[\x20-\x7e]{0,512}$")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        runtime = get_observability_runtime()
        if not runtime.enabled or runtime.http_instrumentation != "manual":
            return await call_next(request)
        request_id = f"req_{uuid4().hex}"
        raw_traceparent = request.headers.get("traceparent")
        raw_tracestate = request.headers.get("tracestate")
        remote = _parse_traceparent(raw_traceparent)
        tracestate = raw_tracestate.strip() if raw_tracestate else None
        if tracestate is not None and not _valid_tracestate(tracestate):
            remote = None
            tracestate = None
        mode = runtime.remote_parent_mode
        trace_override = remote[0] if remote and mode == "continue" else None
        remote_parent_span = remote[1] if remote and mode == "continue" else None
        attributes = {
            "cra.trace.type": "api_request",
            "cra.component": "api",
            "cra.operation": "api.request",
            "cra.request.id": request_id,
            "cra.http.method": request.method,
            "cra.remote_parent.mode": mode,
        }
        handle = start_span_or_root(
            operation="api.request", trace_type="api_request", component="api", kind="server",
            attributes=attributes, request_id=request_id, trace_id_override=trace_override,
            remote_parent_span_id=remote_parent_span,
            trace_flags=remote[2] if remote and mode == "continue" else 0,
            tracestate=tracestate if remote and mode == "continue" else None,
        )
        if remote and mode == "link" and handle.trace_id:
            handle.link(remote[0], linked_span_id=remote[1], relation="linked_from_remote")
        if (raw_traceparent or raw_tracestate) and remote is None:
            handle.event("remote_context_invalid", severity="warning")
        with handle:
            response = await call_next(request)
            route = request.scope.get("route")
            route_path = getattr(route, "path", None)
            event_attributes: dict[str, object] = {"cra.http.status_code": response.status_code}
            if route_path:
                event_attributes["cra.http.route"] = route_path
            handle.event("api.response", attributes=event_attributes)
        response.headers["X-Request-ID"] = request_id
        if handle.trace_id:
            response.headers["X-Trace-ID"] = handle.trace_id
        return response


def _parse_traceparent(value: str | None) -> tuple[str, str, int] | None:
    if not value:
        return None
    match = _TRACEPARENT.fullmatch(value.strip().lower())
    if not match:
        return None
    trace_id, span_id, flags = match.groups()
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id, int(flags, 16)


def _valid_tracestate(value: str) -> bool:
    if not _TRACESTATE.fullmatch(value):
        return False
    members = [item.strip() for item in value.split(",") if item.strip()]
    if len(members) > 32:
        return False
    keys: set[str] = set()
    for member in members:
        if "=" not in member:
            return False
        key, item_value = member.split("=", 1)
        if not key or not item_value or key in keys:
            return False
        keys.add(key)
    return True
