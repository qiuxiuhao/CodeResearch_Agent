from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from backend.app.observability.access_policy import LocalAdminAccessPolicy
from backend.app.observability.context import set_default_recorder
from backend.app.observability.metrics import InMemoryTelemetryMetrics
from backend.app.observability.otel_adapter import OneWayOTelAdapter
from backend.app.observability.recorder import NoopRecorder, TraceRecorder
from backend.app.observability.redaction import HMACHasher, Redactor
from backend.app.observability.sampling import DeterministicSampler
from backend.app.persistence.observability_store import ObservabilityStore


@dataclass(slots=True)
class ObservabilityRuntime:
    enabled: bool
    api_enabled: bool
    recorder: TraceRecorder | NoopRecorder
    store: ObservabilityStore
    access_policy: LocalAdminAccessPolicy
    metrics: InMemoryTelemetryMetrics
    remote_parent_mode: str
    http_instrumentation: str
    otel_adapter: OneWayOTelAdapter
    _enqueue_links: dict[str, tuple[str, str, str]] = field(default_factory=dict, repr=False)
    _enqueue_links_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(cls) -> "ObservabilityRuntime":
        enabled = _bool_env("OBSERVABILITY_ENABLED", False)
        api_enabled = _bool_env("OBSERVABILITY_API_ENABLED", False)
        remote_mode = os.getenv("OBSERVABILITY_REMOTE_PARENT_MODE", "link").strip().lower()
        if remote_mode not in {"continue", "link", "ignore"}:
            raise ValueError("OBSERVABILITY_REMOTE_PARENT_MODE must be continue, link, or ignore")
        instrumentation = os.getenv("OBSERVABILITY_HTTP_INSTRUMENTATION", "manual").strip().lower()
        if instrumentation not in {"manual", "otel_auto"}:
            raise ValueError("OBSERVABILITY_HTTP_INSTRUMENTATION must be manual or otel_auto")
        store = ObservabilityStore(
            os.getenv("OBSERVABILITY_DB_PATH", "data/observability.sqlite3"),
            busy_timeout_ms=int(os.getenv("OBSERVABILITY_BUSY_TIMEOUT_MS", "2000")),
        )
        key_value = os.getenv("OBSERVABILITY_HMAC_KEY")
        key_id = os.getenv("OBSERVABILITY_HMAC_KEY_ID") if key_value else None
        redactor = Redactor(HMACHasher(key_id=key_id, key=key_value.encode() if key_value else None))
        sampler = DeterministicSampler(
            metadata_enabled=enabled,
            diagnostic_rate=float(os.getenv("OBSERVABILITY_DIAGNOSTIC_SAMPLE_RATE", "0")),
            otlp_rate=float(os.getenv("OBSERVABILITY_OTLP_SAMPLE_RATE", "0")),
        )
        metrics = InMemoryTelemetryMetrics()
        otel_adapter = OneWayOTelAdapter(
            enabled=enabled and _bool_env("OBSERVABILITY_OTLP_ENABLED", False),
            endpoint=os.getenv("OBSERVABILITY_OTLP_ENDPOINT"),
        )
        recorder: TraceRecorder | NoopRecorder
        if enabled:
            recorder = TraceRecorder(
                store,
                sampler=sampler,
                redactor=redactor,
                queue_size=int(os.getenv("OBSERVABILITY_QUEUE_SIZE", "4096")),
                batch_size=int(os.getenv("OBSERVABILITY_BATCH_SIZE", "128")),
                flush_interval_seconds=float(os.getenv("OBSERVABILITY_FLUSH_INTERVAL_SECONDS", "0.25")),
                otel_adapter=otel_adapter,
                retention_seconds=int(os.getenv("OBSERVABILITY_RETENTION_SECONDS", "1209600")),
                retention_interval_seconds=float(
                    os.getenv("OBSERVABILITY_RETENTION_INTERVAL_SECONDS", "3600")
                ),
                slow_trace_threshold_ms=float(
                    os.getenv("OBSERVABILITY_SLOW_TRACE_THRESHOLD_MS", "5000")
                ),
                metrics=metrics,
            )
        else:
            recorder = NoopRecorder()
        return cls(
            enabled=enabled, api_enabled=api_enabled, recorder=recorder, store=store,
            access_policy=LocalAdminAccessPolicy(), metrics=metrics,
            remote_parent_mode=remote_mode, http_instrumentation=instrumentation,
            otel_adapter=otel_adapter,
        )

    def start(self) -> None:
        try:
            self.otel_adapter.start()
        except Exception:
            self.metrics.increment("observability_otlp_start_failure")
            self.otel_adapter.enabled = False
        try:
            self.recorder.start()
        except Exception:
            self.metrics.increment("observability_runtime_start_failure")
            self.recorder = NoopRecorder()
        set_default_recorder(self.recorder)

    def stop(self) -> None:
        try:
            self.recorder.stop(timeout=float(os.getenv("OBSERVABILITY_SHUTDOWN_FLUSH_SECONDS", "3")))
        except Exception:
            self.metrics.increment("observability_runtime_stop_failure")
        try:
            self.otel_adapter.shutdown(
                int(float(os.getenv("OBSERVABILITY_SHUTDOWN_FLUSH_SECONDS", "3")) * 1_000)
            )
        except Exception:
            self.metrics.increment("observability_otlp_shutdown_failure")
        set_default_recorder(NoopRecorder())

    def register_enqueue_link(
        self,
        business_id: str,
        trace_id: str,
        span_id: str,
        *,
        relation: str = "queued_from",
    ) -> None:
        """Keep a bounded, process-local correlation for a newly queued background job."""
        if not self.enabled:
            return
        with self._enqueue_links_lock:
            if len(self._enqueue_links) >= 4_096:
                self._enqueue_links.pop(next(iter(self._enqueue_links)))
            self._enqueue_links[business_id] = (trace_id, span_id, relation)

    def consume_enqueue_link(self, business_id: str) -> tuple[str, str, str] | None:
        with self._enqueue_links_lock:
            return self._enqueue_links.pop(business_id, None)


_runtime: ObservabilityRuntime | None = None


def get_observability_runtime() -> ObservabilityRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ObservabilityRuntime.from_env()
    return _runtime


def reset_observability_runtime() -> None:
    global _runtime
    if _runtime is not None:
        _runtime.stop()
    _runtime = None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
