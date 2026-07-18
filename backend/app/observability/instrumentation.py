from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from backend.app.observability.context import current_trace_context, start_span_or_root
from backend.app.observability.schemas import SpanComponent


T = TypeVar("T")


def observe_child_call(
    operation: str,
    *,
    component: SpanComponent,
    callback: Callable[[], T],
    attributes: dict[str, object] | None = None,
) -> T:
    """Observe a nested adapter call without ever creating an independent root trace."""
    context = current_trace_context()
    if context is None:
        return callback()
    handle = start_span_or_root(
        operation=operation,
        trace_type=context.trace_type,
        component=component,
        parent_context=context,
        attributes=attributes,
    )
    with handle:
        return callback()
