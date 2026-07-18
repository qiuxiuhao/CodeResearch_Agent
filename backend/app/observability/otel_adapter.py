from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from backend.app.observability.schemas import TelemetryCommand
from backend.app.observability.suppression import suppress_observability


class OTelAdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class OneWayOTelAdapter:
    """Optional one-way bridge from validated internal commands to OTel spans."""

    enabled: bool = False
    endpoint: str | None = None
    service_version: str = "1.8.0"
    _provider: Any = field(default=None, init=False, repr=False)
    _tracer: Any = field(default=None, init=False, repr=False)
    _spans: dict[tuple[str, str], Any] = field(default_factory=dict, init=False, repr=False)
    _sampled_traces: set[str] = field(default_factory=set, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            raise OTelAdapterError("opentelemetry_dependency_missing") from exc
        resource = Resource.create(
            {
                "service.name": "code-research-agent",
                "service.version": self.service_version,
                "cra.attribute_registry.version": "cra-attributes-v1",
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=self.endpoint) if self.endpoint else OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        self._provider = provider
        self._tracer = provider.get_tracer("code-research-agent.observability", self.service_version)
        # Do not replace an application-wide global provider. The internal adapter owns its
        # provider directly and therefore cannot create an OTel -> internal SQLite loop.
        _ = trace

    def accept(self, command: TelemetryCommand) -> None:
        if not self.enabled or self._tracer is None:
            return
        try:
            with suppress_observability(), self._lock:
                self._accept_validated(command)
        except Exception:
            # External telemetry is strictly best effort.
            return

    def _accept_validated(self, command: TelemetryCommand) -> None:
        payload = command.payload
        if command.command_type == "trace_start":
            if bool(payload.get("otlp_sampled")):
                self._sampled_traces.add(command.trace_id)
            return
        if command.trace_id not in self._sampled_traces:
            return
        key = (command.trace_id, command.span_id or "")
        if command.command_type == "span_start":
            parent_key = (command.trace_id, str(payload.get("parent_span_id") or ""))
            parent = self._spans.get(parent_key)
            context = None
            if parent is not None:
                from opentelemetry import trace

                context = trace.set_span_in_context(parent)
            attributes = dict(payload.get("attributes") or {})
            attributes["cra.internal.trace_id"] = command.trace_id
            attributes["cra.internal.span_id"] = command.span_id or ""
            self._spans[key] = self._tracer.start_span(
                str(payload.get("name") or "cra.operation"),
                context=context,
                attributes=attributes,
            )
            return
        if command.command_type == "trace_end":
            self._sampled_traces.discard(command.trace_id)
            return
        span = self._spans.get(key)
        if span is None:
            return
        if command.command_type == "span_event":
            span.add_event(
                str(payload.get("name") or "cra.event"),
                attributes=dict(payload.get("attributes") or {}),
            )
        elif command.command_type == "span_link":
            span.add_event(
                "cra.span_link",
                attributes={
                    "cra.link.trace_id": str(payload.get("linked_trace_id") or ""),
                    "cra.link.relation": str(payload.get("relation") or "continued_from"),
                },
            )
        elif command.command_type == "artifact_ref":
            span.add_event(
                "cra.artifact_ref",
                attributes={
                    "cra.artifact.type": str(payload.get("artifact_type") or "artifact"),
                    "cra.artifact.id": str(payload.get("artifact_id") or "")[:512],
                },
            )
        elif command.command_type == "span_end":
            if payload.get("status") == "error":
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(payload.get("error_code") or "error")))
            span.end()
            self._spans.pop(key, None)

    def shutdown(self, timeout_ms: int = 3_000) -> None:
        if self._provider is None:
            return
        with suppress_observability():
            try:
                self._provider.force_flush(timeout_millis=max(0, timeout_ms))
                self._provider.shutdown()
            finally:
                self._provider = None
                self._tracer = None
                self._spans.clear()
                self._sampled_traces.clear()
