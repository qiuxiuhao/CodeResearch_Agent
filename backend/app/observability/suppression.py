from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator


_suppressed: ContextVar[bool] = ContextVar("observability_suppressed", default=False)


def observability_suppressed() -> bool:
    return _suppressed.get()


@contextmanager
def suppress_observability() -> Iterator[None]:
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)
