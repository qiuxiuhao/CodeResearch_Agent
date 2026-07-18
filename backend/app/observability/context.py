from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any

from backend.app.observability.schemas import SpanComponent, TraceContext, TraceType
from backend.app.observability.suppression import observability_suppressed

if TYPE_CHECKING:
    from backend.app.observability.recorder import BaseRecorder, SpanHandle


_current_context: ContextVar[TraceContext | None] = ContextVar("cra_trace_context", default=None)
_default_recorder: Any = None


def current_trace_context() -> TraceContext | None:
    return _current_context.get()


def set_default_recorder(recorder: "BaseRecorder") -> None:
    global _default_recorder
    _default_recorder = recorder


def get_default_recorder() -> "BaseRecorder":
    if _default_recorder is None:
        from backend.app.observability.recorder import NoopRecorder

        return NoopRecorder()
    return _default_recorder


def start_span_or_root(
    *,
    operation: str,
    trace_type: TraceType,
    component: SpanComponent,
    parent_context: TraceContext | None = None,
    attributes: dict[str, object] | None = None,
    kind: str = "internal",
    request_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    repo_id: str | None = None,
    index_version_id: str | None = None,
    caller_scope_hash: str | None = None,
    trace_id_override: str | None = None,
    remote_parent_span_id: str | None = None,
    trace_flags: int = 0,
    tracestate: str | None = None,
    force_root: bool = False,
) -> "SpanHandle":
    recorder = get_default_recorder()
    if observability_suppressed():
        return recorder.noop_span()
    parent = None if force_root else (
        parent_context if parent_context is not None else current_trace_context()
    )
    return recorder.start_span(
        operation=operation,
        trace_type=trace_type,
        component=component,
        parent_context=parent,
        attributes=attributes or {},
        kind=kind,
        request_id=request_id,
        run_id=run_id,
        task_id=task_id,
        repo_id=repo_id,
        index_version_id=index_version_id,
        caller_scope_hash=caller_scope_hash,
        trace_id_override=trace_id_override,
        remote_parent_span_id=remote_parent_span_id,
        trace_flags=trace_flags,
        tracestate=tracestate,
    )


def _activate_context(context: TraceContext) -> Token:
    return _current_context.set(context)


def _reset_context(token: Token) -> None:
    _current_context.reset(token)
