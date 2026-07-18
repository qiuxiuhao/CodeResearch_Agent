from __future__ import annotations

import threading
from collections import Counter

from backend.app.observability.schemas import TelemetryCommand


class InMemoryTelemetryMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {**dict(self._counters), **self._gauges}

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def observe(self, command: TelemetryCommand) -> None:
        payload = command.payload
        if command.command_type == "trace_start":
            self.increment(f"trace.started.{payload.get('trace_type', 'unknown')}")
        elif command.command_type == "trace_end":
            self.increment(f"trace.terminal.{payload.get('status', 'unknown')}")
        elif command.command_type == "span_start":
            self.increment(f"span.started.{payload.get('component', 'unknown')}")
        elif command.command_type == "span_event":
            name = str(payload.get("name") or "unknown")
            self.increment(f"event.{name}")
            attributes = payload.get("attributes") or {}
            if isinstance(attributes, dict):
                for key, metric in (
                    ("cra.token.input", "provider.token.input"),
                    ("cra.token.output", "provider.token.output"),
                    ("cra.token.total", "provider.token.total"),
                    ("cra.candidate.count", "retrieval.candidate.total"),
                ):
                    value = attributes.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        self.increment(metric, value)
