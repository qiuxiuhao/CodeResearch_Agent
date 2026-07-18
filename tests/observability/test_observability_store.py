from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from backend.app.observability.schemas import TelemetryCommand
from backend.app.persistence.observability_store import ObservabilityStore


def test_duplicate_span_start_is_idempotent(tmp_path):
    store, trace_id, root_id = _running_trace(tmp_path)
    command = _span_start(trace_id, "3" * 16, command_id="child-start")
    assert store.apply_commands([command, command]) == 1
    assert len(store.list_spans(trace_id, limit=20)) == 2


def test_duplicate_span_end_is_idempotent(tmp_path):
    store, trace_id, _ = _running_trace(tmp_path)
    child = "3" * 16
    store.apply_commands([_span_start(trace_id, child, command_id="child-start")])
    terminal = _span_end(trace_id, child, "child-end", "ok")
    assert store.apply_commands([terminal, terminal]) == 1
    assert store.get_span(trace_id, child).status == "ok"


def test_conflicting_terminal_span_end_is_rejected(tmp_path):
    store, trace_id, _ = _running_trace(tmp_path)
    child = "3" * 16
    store.apply_commands([_span_start(trace_id, child), _span_end(trace_id, child, "end-ok", "ok")])
    store.apply_commands([_span_end(trace_id, child, "end-error", "error")])
    assert store.get_span(trace_id, child).status == "ok"
    assert "store_failure" in store.get_trace(trace_id).integrity_flags


def test_span_end_before_start_is_handled_deterministically(tmp_path):
    store, trace_id, _ = _running_trace(tmp_path)
    child = "3" * 16
    store.apply_commands([
        _span_end(trace_id, child, "early-end", "ok"),
        _span_start(trace_id, child, command_id="late-start"),
    ])
    assert store.get_span(trace_id, child).status == "ok"


def test_batch_retry_does_not_duplicate_events(tmp_path):
    store, trace_id, root_id = _running_trace(tmp_path)
    event = _event(trace_id, root_id, "event-command", "evt-one")
    store.apply_commands([event])
    store.apply_commands([event])
    items = store.list_events(trace_id)
    assert [(item.event_id, item.stream_sequence) for item in items] == [("evt-one", 1)]


def test_concurrent_event_producers_get_unique_stream_sequence(tmp_path):
    store, trace_id, root_id = _running_trace(tmp_path)
    commands = [_event(trace_id, root_id, f"cmd-{index}", f"evt-{index}") for index in range(20)]
    threads = [threading.Thread(target=store.apply_commands, args=([command],)) for command in commands]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    sequences = [item.stream_sequence for item in store.list_events(trace_id, limit=100)]
    assert sequences == list(range(1, 21))


def test_stream_sequence_is_monotonic_per_trace(tmp_path):
    store, trace_id, root_id = _running_trace(tmp_path)
    store.apply_commands([_event(trace_id, root_id, "a", "same")])
    store.apply_commands([_event(trace_id, root_id, "b", "same")])
    store.apply_commands([_event(trace_id, root_id, "c", "other")])
    assert [item.stream_sequence for item in store.list_events(trace_id)] == [1, 2]


def test_running_span_becomes_abandoned_after_crash(tmp_path):
    store, trace_id, root_id = _running_trace(tmp_path, started=datetime.now(UTC) - timedelta(minutes=2))
    assert store.abandon_running(older_than_seconds=30) >= 1
    assert store.get_span(trace_id, root_id).status == "abandoned"
    trace = store.get_trace(trace_id)
    assert trace.status == "abandoned"
    assert trace.duration_estimated is True
    assert "process_crash" in trace.integrity_flags


def test_queue_drop_marks_trace_partial(tmp_path):
    store, trace_id, _ = _running_trace(tmp_path)
    store.mark_integrity(trace_id, "queue_drop", dropped=3)
    trace = store.get_trace(trace_id)
    assert trace.completeness == "partial"
    assert trace.dropped_record_count == 3


def test_complete_trace_has_no_integrity_flags(tmp_path):
    store, trace_id, root_id = _running_trace(tmp_path)
    store.apply_commands([_span_end(trace_id, root_id, "root-end", "ok"), _trace_end(trace_id, root_id)])
    trace = store.get_trace(trace_id)
    assert trace.completeness == "complete"
    assert trace.integrity_flags == []


def _running_trace(tmp_path, *, started: datetime | None = None):
    store = ObservabilityStore(tmp_path / "observability.sqlite3", busy_timeout_ms=5_000)
    store.migrate()
    trace_id, root_id = "1" * 32, "2" * 16
    now = started or datetime.now(UTC)
    store.apply_commands([
        TelemetryCommand(command_id="trace-start", command_type="trace_start", trace_id=trace_id, lifecycle_sequence=1, occurred_at=now, payload={"trace_type": "retrieval", "root_span_id": root_id, "recording_mode": "metadata"}),
        _span_start(trace_id, root_id, command_id="root-start", occurred_at=now),
    ])
    return store, trace_id, root_id


def _span_start(trace_id, span_id, command_id="span-start", occurred_at=None):
    return TelemetryCommand(command_id=command_id, command_type="span_start", trace_id=trace_id, span_id=span_id, lifecycle_sequence=1, occurred_at=occurred_at or datetime.now(UTC), payload={"name": "test.span", "component": "retrieval", "kind": "internal", "attributes": {}})


def _span_end(trace_id, span_id, command_id, status):
    return TelemetryCommand(command_id=command_id, command_type="span_end", trace_id=trace_id, span_id=span_id, lifecycle_sequence=2, occurred_at=datetime.now(UTC), payload={"status": status, "duration_ms": 1.0, "duration_estimated": False})


def _trace_end(trace_id, root_id):
    return TelemetryCommand(command_id="trace-end", command_type="trace_end", trace_id=trace_id, span_id=root_id, lifecycle_sequence=2, occurred_at=datetime.now(UTC), payload={"status": "completed", "duration_ms": 1.0, "duration_estimated": False})


def _event(trace_id, span_id, command_id, event_id):
    return TelemetryCommand(command_id=command_id, command_type="span_event", trace_id=trace_id, span_id=span_id, lifecycle_sequence=2, occurred_at=datetime.now(UTC), payload={"event_id": event_id, "name": "test.event", "severity": "info", "attributes": {}, "size_bytes": 2})
