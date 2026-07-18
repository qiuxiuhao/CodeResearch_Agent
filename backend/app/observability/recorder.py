from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from backend.app.observability.attributes import (
    OPERATION_TAXONOMY_VERSION,
    REGISTRY_VERSION,
    AttributeRegistry,
)
from backend.app.observability.redaction import Redactor
from backend.app.observability.sampling import DeterministicSampler
from backend.app.observability.schemas import (
    RecordingDecision,
    SpanComponent,
    TelemetryCommand,
    TraceContext,
    TraceType,
)
from backend.app.persistence.observability_store import ObservabilityStore


def _trace_id() -> str:
    return uuid4().hex


def _span_id() -> str:
    return uuid4().hex[:16]


def _command_id() -> str:
    return f"cmd_{uuid4().hex}"


def _now() -> datetime:
    return datetime.now(UTC)


class BaseRecorder(Protocol):
    def start_span(self, **kwargs) -> "SpanHandle": ...
    def noop_span(self) -> "SpanHandle": ...


class SpanHandle(AbstractContextManager, AbstractAsyncContextManager):
    def __init__(
        self,
        recorder: "TraceRecorder | None",
        context: TraceContext | None = None,
        *,
        root: bool = False,
        operation: str = "noop",
        component: SpanComponent = "api",
    ) -> None:
        self.recorder = recorder
        self.context = context
        self.root = root
        self.operation = operation
        self.component = component
        self._token = None
        self._started_monotonic = time.perf_counter_ns()
        self._ended = False
        self._producer_sequence = 0

    @property
    def trace_id(self) -> str | None:
        return self.context.trace_id if self.context else None

    @property
    def span_id(self) -> str | None:
        return self.context.span_id if self.context else None

    def __enter__(self) -> "SpanHandle":
        if self.context is not None:
            from backend.app.observability.context import _activate_context

            self._token = _activate_context(self.context)
        return self

    async def __aenter__(self) -> "SpanHandle":
        return self.__enter__()

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc is None:
                self.end(status="ok")
            else:
                self.end(status="error", error=exc)
        finally:
            if self._token is not None:
                from backend.app.observability.context import _reset_context

                _reset_context(self._token)
                self._token = None
        return None

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.__exit__(exc_type, exc, traceback)

    def end(
        self,
        *,
        status: str = "ok",
        error: BaseException | None = None,
        error_code: str | None = None,
        completion_status: str | None = None,
        duration_override_ms: float | None = None,
    ) -> None:
        if self._ended or self.recorder is None or self.context is None:
            return
        if self.root:
            self.event(
                "trace.terminal",
                attributes={
                    "cra.status": completion_status or status,
                    **({"cra.error.code": error_code} if error_code else {}),
                },
            )
        self._ended = True
        duration_ms = (
            duration_override_ms
            if duration_override_ms is not None
            else (time.perf_counter_ns() - self._started_monotonic) / 1_000_000
        )
        if self.root and duration_ms >= self.recorder.slow_trace_threshold_ms:
            self.event("trace.slow", attributes={"cra.duration.ms": duration_ms})
        exception_type = template = error_hash = None
        if error is not None:
            exception_type, template, error_hash = self.recorder.redactor.safe_error(
                error, error_code=error_code
            )
        sequence = 2
        self.recorder.submit(
            TelemetryCommand(
                command_id=_command_id(),
                command_type="span_end",
                trace_id=self.context.trace_id,
                span_id=self.context.span_id,
                lifecycle_sequence=sequence,
                occurred_at=_now(),
                payload={
                    "status": status,
                    "completion_status": completion_status,
                    "duration_ms": max(0.0, duration_ms),
                    "duration_estimated": False,
                    "error_code": error_code,
                    "exception_type": exception_type,
                    "error_message_template": template,
                    "error_message_hash": error_hash,
                },
            )
        )
        if self.root:
            trace_status = {
                "ok": "completed",
                "error": "failed",
                "cancelled": "cancelled",
                "abandoned": "abandoned",
            }.get(status, "partial")
            if completion_status == "partial":
                trace_status = "partial"
            self.recorder.submit(
                TelemetryCommand(
                    command_id=_command_id(),
                    command_type="trace_end",
                    trace_id=self.context.trace_id,
                    span_id=self.context.span_id,
                    lifecycle_sequence=2,
                    occurred_at=_now(),
                    payload={
                        "status": trace_status,
                        "completion_status": completion_status,
                        "duration_ms": max(0.0, duration_ms),
                        "duration_estimated": False,
                        "error_code": error_code,
                    },
                )
            )

    def event(
        self, name: str, *, severity: str = "info", attributes: dict[str, object] | None = None
    ) -> None:
        if self.recorder is None or self.context is None:
            return
        self._producer_sequence += 1
        values = self.recorder.clean_attributes(attributes or {})
        size = len(json.dumps(values, ensure_ascii=False).encode("utf-8"))
        while size > 8 * 1024 and values:
            values.pop(next(reversed(values)))
            size = len(json.dumps(values, ensure_ascii=False).encode("utf-8"))
        self.recorder.submit(
            TelemetryCommand(
                command_id=_command_id(), command_type="span_event",
                trace_id=self.context.trace_id, span_id=self.context.span_id,
                lifecycle_sequence=max(2, self._producer_sequence + 1), occurred_at=_now(),
                payload={
                    "event_id": f"evt_{uuid4().hex}", "producer_sequence": self._producer_sequence,
                    "name": name[:160], "severity": severity, "attributes": values,
                    "size_bytes": size,
                },
            )
        )

    def link(
        self,
        linked_trace_id: str,
        *,
        relation: str,
        linked_span_id: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> None:
        if self.recorder is None or self.context is None:
            return
        self.recorder.submit(
            TelemetryCommand(
                command_id=_command_id(), command_type="span_link",
                trace_id=self.context.trace_id, span_id=self.context.span_id,
                lifecycle_sequence=1, occurred_at=_now(),
                payload={
                    "link_id": f"link_{uuid4().hex}", "linked_trace_id": linked_trace_id,
                    "linked_span_id": linked_span_id, "relation": relation,
                    "attributes": self.recorder.clean_attributes(attributes or {}),
                },
            )
        )

    def artifact(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        role: str,
        content_hash: str | None = None,
        repo_id: str | None = None,
        index_version_id: str | None = None,
    ) -> None:
        if self.recorder is None or self.context is None:
            return
        self.recorder.submit(
            TelemetryCommand(
                command_id=_command_id(), command_type="artifact_ref",
                trace_id=self.context.trace_id, span_id=self.context.span_id,
                lifecycle_sequence=1, occurred_at=_now(),
                payload={
                    "ref_id": f"ref_{uuid4().hex}", "artifact_type": artifact_type,
                    "artifact_id": artifact_id[:512], "content_hash": content_hash,
                    "repo_id": repo_id, "index_version_id": index_version_id, "role": role[:128],
                },
            )
        )

    def completed_child(
        self,
        operation: str,
        *,
        component: SpanComponent,
        duration_ms: float,
        attributes: dict[str, object] | None = None,
    ) -> None:
        if self.recorder is None or self.context is None:
            return
        child = self.recorder.start_span(
            operation=operation, trace_type=self.context.trace_type, component=component,
            parent_context=self.context, attributes=attributes or {}, kind="internal",
        )
        child.end(status="ok", duration_override_ms=duration_ms)


class NoopRecorder:
    def start_span(self, **kwargs) -> SpanHandle:
        return self.noop_span()

    def noop_span(self) -> SpanHandle:
        return SpanHandle(None)

    def start(self) -> None:
        return None

    def stop(self, timeout: float = 0.0) -> None:
        return None

    def flush(self, timeout: float = 0.0) -> bool:
        return True


class TraceRecorder:
    def __init__(
        self,
        store: ObservabilityStore,
        *,
        sampler: DeterministicSampler,
        redactor: Redactor,
        queue_size: int = 4_096,
        batch_size: int = 128,
        flush_interval_seconds: float = 0.25,
        otel_adapter=None,
        retention_seconds: int = 14 * 24 * 60 * 60,
        retention_interval_seconds: float = 60 * 60,
        slow_trace_threshold_ms: float = 5_000,
        metrics=None,
    ) -> None:
        self.store = store
        self.sampler = sampler
        self.redactor = redactor
        self.registry = AttributeRegistry()
        self.queue: queue.Queue[TelemetryCommand] = queue.Queue(maxsize=max(32, queue_size))
        self.batch_size = max(1, batch_size)
        self.flush_interval_seconds = max(0.01, flush_interval_seconds)
        self.otel_adapter = otel_adapter
        self.retention_seconds = max(60, retention_seconds)
        self.retention_interval_seconds = max(10.0, retention_interval_seconds)
        self._next_retention = time.monotonic() + self.retention_interval_seconds
        self.slow_trace_threshold_ms = max(0.0, slow_trace_threshold_ms)
        self.metrics = metrics
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._integrity_lock = threading.Lock()
        self._dropped: dict[str, int] = {}
        self._integrity_flags: dict[str, set[str]] = {}
        self.store_failure_count = 0

    def start(self) -> None:
        self.store.migrate()
        self.store.abandon_running()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._writer_loop, name="observability-writer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self.flush(timeout)
        if self._thread:
            self._thread.join(timeout=max(0.0, timeout))
        self._thread = None

    def noop_span(self) -> SpanHandle:
        return SpanHandle(None)

    def start_span(
        self,
        *,
        operation: str,
        trace_type: TraceType,
        component: SpanComponent,
        parent_context: TraceContext | None,
        attributes: dict[str, object],
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
    ) -> SpanHandle:
        if parent_context is None:
            trace_id = trace_id_override or _trace_id()
            decision = self.sampler.decide(trace_id, trace_type)
            if not decision.record_metadata:
                return self.noop_span()
            span_id = _span_id()
            context = TraceContext(
                trace_id=trace_id, span_id=span_id, trace_type=trace_type,
                request_id=request_id, run_id=run_id, task_id=task_id,
                repo_id=repo_id, index_version_id=index_version_id,
                caller_scope_hash=caller_scope_hash, recording=decision,
                trace_flags=trace_flags,
                tracestate=tracestate,
            )
            cleaned = self.clean_attributes(attributes, diagnostics=decision.record_diagnostics)
            now = _now()
            self.submit(TelemetryCommand(
                command_id=_command_id(), command_type="trace_start", trace_id=trace_id,
                span_id=None, lifecycle_sequence=1, occurred_at=now,
                payload={
                    "trace_type": trace_type, "root_span_id": span_id, "request_id": request_id,
                    "run_id": run_id, "task_id": task_id, "repo_id": repo_id,
                    "index_version_id": index_version_id, "caller_scope_hash": caller_scope_hash,
                    "recording_mode": "diagnostic_metadata" if decision.record_diagnostics else "metadata",
                    "diagnostic_sampled": decision.record_diagnostics,
                    "otlp_sampled": decision.export_otlp,
                    "attribute_registry_version": REGISTRY_VERSION,
                    "operation_taxonomy_version": OPERATION_TAXONOMY_VERSION,
                    "hash_key_id": self.redactor.hasher.key_id,
                    "hash_algorithm": self.redactor.hasher.algorithm if self.redactor.hasher.key_id else None,
                    "attributes": cleaned,
                },
            ))
            parent_span_id = remote_parent_span_id
            root = True
        else:
            context = parent_context.model_copy(update={"span_id": _span_id()})
            trace_id = context.trace_id
            span_id = context.span_id
            cleaned = self.clean_attributes(
                attributes, diagnostics=context.recording.record_diagnostics
            )
            now = _now()
            parent_span_id = parent_context.span_id
            root = False
        self.submit(TelemetryCommand(
            command_id=_command_id(), command_type="span_start", trace_id=trace_id,
            span_id=span_id, lifecycle_sequence=1, occurred_at=now,
            payload={
                "parent_span_id": parent_span_id, "name": operation[:160],
                "component": component, "kind": kind, "attributes": cleaned,
            },
        ))
        return SpanHandle(self, context, root=root, operation=operation, component=component)

    def clean_attributes(
        self, attributes: dict[str, object], *, diagnostics: bool = False
    ) -> dict[str, object]:
        redacted = self.redactor.redact_attributes(attributes)
        return cast(dict[str, object], self.registry.sanitize(redacted, diagnostics=diagnostics))

    def submit(self, command: TelemetryCommand) -> None:
        if self.metrics is not None:
            self.metrics.observe(command)
        if self.otel_adapter is not None:
            try:
                self.otel_adapter.accept(command)
            except Exception:
                self.store_failure_count += 1
        try:
            self.queue.put_nowait(command)
            if self.metrics is not None:
                self.metrics.set_gauge("telemetry.queue.depth", float(self.queue.qsize()))
        except queue.Full:
            if command.command_type in {"span_end", "trace_end"}:
                try:
                    displaced = self.queue.get_nowait()
                    self.queue.task_done()
                    self._record_drop(displaced.trace_id, "queue_drop")
                    self.queue.put_nowait(command)
                    return
                except queue.Empty:
                    pass
                except queue.Full:
                    pass
            self._record_drop(command.trace_id, "queue_drop")

    def flush(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while self.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.queue.unfinished_tasks == 0

    def _writer_loop(self) -> None:
        while not self._stop.is_set() or not self.queue.empty():
            batch: list[TelemetryCommand] = []
            try:
                first = self.queue.get(timeout=self.flush_interval_seconds)
                batch.append(first)
                while len(batch) < self.batch_size:
                    try:
                        batch.append(self.queue.get_nowait())
                    except queue.Empty:
                        break
                failure: Exception | None = None
                for attempt in range(3):
                    try:
                        self.store.apply_commands(batch)
                        failure = None
                        break
                    except Exception as exc:
                        failure = exc
                        if attempt < 2:
                            time.sleep(0.01 * (attempt + 1))
                if failure is not None:
                    raise failure
            except queue.Empty:
                pass
            except Exception:
                self.store_failure_count += 1
                for command in batch:
                    self._record_drop(command.trace_id, "store_failure")
            finally:
                for _item in batch:
                    self.queue.task_done()
                if self.metrics is not None:
                    self.metrics.set_gauge("telemetry.queue.depth", float(self.queue.qsize()))
            self._drain_integrity()
            if time.monotonic() >= self._next_retention:
                try:
                    self.store.delete_before(
                        datetime.now(UTC) - timedelta(seconds=self.retention_seconds), limit=500
                    )
                except Exception:
                    self.store_failure_count += 1
                self._next_retention = time.monotonic() + self.retention_interval_seconds

    def _drain_integrity(self) -> None:
        with self._integrity_lock:
            dropped, self._dropped = self._dropped, {}
            flags, self._integrity_flags = self._integrity_flags, {}
        for trace_id, trace_flags in flags.items():
            try:
                for flag in sorted(trace_flags):
                    self.store.mark_integrity(
                        trace_id,
                        flag,
                        dropped=dropped.get(trace_id, 0) if flag == "queue_drop" else 0,
                    )
            except Exception:
                self.store_failure_count += 1

    def _record_drop(self, trace_id: str, flag: str) -> None:
        with self._integrity_lock:
            self._dropped[trace_id] = self._dropped.get(trace_id, 0) + 1
            self._integrity_flags.setdefault(trace_id, set()).add(flag)
        if self.metrics is not None:
            self.metrics.increment(f"telemetry.drop.{flag}")


class InMemoryRecorder(TraceRecorder):
    """Deterministic, synchronous recorder for unit tests; it performs no I/O."""

    def __init__(
        self,
        *,
        sampler: DeterministicSampler | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        from backend.app.observability.redaction import HMACHasher

        super().__init__(
            cast(ObservabilityStore, _InMemoryStore()),
            sampler=sampler or DeterministicSampler(),
            redactor=redactor or Redactor(HMACHasher(key_id=None, key=None)),
        )
        self.commands: list[TelemetryCommand] = []

    def start(self) -> None:
        return None

    def stop(self, timeout: float = 0.0) -> None:
        return None

    def submit(self, command: TelemetryCommand) -> None:
        self.commands.append(command)

    def flush(self, timeout: float = 0.0) -> bool:
        return True


class _InMemoryStore:
    def migrate(self) -> None:
        return None

    def abandon_running(self) -> int:
        return 0
