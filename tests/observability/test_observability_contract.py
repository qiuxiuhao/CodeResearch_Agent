from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.observability.context import set_default_recorder, start_span_or_root
from backend.app.observability.middleware import _parse_traceparent, _valid_tracestate
from backend.app.observability.recorder import InMemoryRecorder, NoopRecorder
from backend.app.observability.redaction import HMACHasher, Redactor
from backend.app.observability.sampling import DeterministicSampler
from backend.app.observability.schemas import TelemetryCommand
from backend.app.observability.suppression import suppress_observability


@pytest.fixture
def recorder():
    value = InMemoryRecorder(sampler=DeterministicSampler(metadata_enabled=True))
    set_default_recorder(value)
    try:
        yield value
    finally:
        set_default_recorder(NoopRecorder())


def test_retrieval_inside_agent_does_not_create_second_root(recorder):
    with start_span_or_root(
        operation="agent.run", trace_type="research_agent", component="agent"
    ) as root:
        with start_span_or_root(
            operation="retrieval.search", trace_type="retrieval", component="retrieval"
        ) as child:
            assert child.trace_id == root.trace_id
    assert len(_commands(recorder, "trace_start")) == 1
    starts = _commands(recorder, "span_start")
    assert starts[1].payload["parent_span_id"] == starts[0].span_id


def test_retrieval_inside_alignment_is_child_span(recorder):
    with start_span_or_root(
        operation="alignment.run", trace_type="alignment", component="alignment"
    ) as root:
        with start_span_or_root(
            operation="retrieval.search", trace_type="retrieval", component="retrieval"
        ) as child:
            assert child.trace_id == root.trace_id
            assert child.context.trace_type == "alignment"


def test_standalone_retrieval_creates_root(recorder):
    with start_span_or_root(
        operation="retrieval.search", trace_type="retrieval", component="retrieval"
    ):
        pass
    assert len(_commands(recorder, "trace_start")) == 1


@pytest.mark.parametrize("operation", ["analysis.run", "agent.run"])
def test_background_analysis_links_to_enqueue_api(recorder, operation):
    with start_span_or_root(
        operation="api.request", trace_type="api_request", component="api"
    ) as api:
        api_trace = api.trace_id
        api_span = api.span_id
    with start_span_or_root(
        operation=operation,
        trace_type="analysis" if operation.startswith("analysis") else "research_agent",
        component="analysis_graph" if operation.startswith("analysis") else "agent",
        force_root=True,
    ) as background:
        background.link(api_trace, linked_span_id=api_span, relation="queued_from")
    assert len(_commands(recorder, "trace_start")) == 2
    link = _commands(recorder, "span_link")[0]
    assert link.payload["relation"] == "queued_from"


def test_background_agent_links_to_enqueue_api(recorder):
    test_background_analysis_links_to_enqueue_api(recorder, "agent.run")


def test_remote_parent_link_mode_creates_local_trace(recorder):
    remote_trace = "1" * 32
    with start_span_or_root(
        operation="api.request", trace_type="api_request", component="api", force_root=True
    ) as local:
        local.link(remote_trace, linked_span_id="2" * 16, relation="linked_from_remote")
        assert local.trace_id != remote_trace


def test_remote_parent_continue_mode_uses_remote_trace(recorder):
    remote_trace = "1" * 32
    with start_span_or_root(
        operation="api.request", trace_type="api_request", component="api",
        trace_id_override=remote_trace, remote_parent_span_id="2" * 16,
        trace_flags=1, force_root=True,
    ) as local:
        assert local.trace_id == remote_trace
        assert local.context.trace_flags == 1


def test_invalid_traceparent_is_ignored_safely():
    assert _parse_traceparent("00-not-a-trace") is None
    assert _parse_traceparent(f"00-{'0' * 32}-{'1' * 16}-01") is None
    assert not _valid_tracestate("missing-equals")


def test_remote_context_never_changes_access_control():
    # Parsing correlation data returns IDs only; it never produces caller/repository identity.
    parsed = _parse_traceparent(f"00-{'1' * 32}-{'2' * 16}-01")
    assert parsed == ("1" * 32, "2" * 16, 1)


def test_observability_store_does_not_trace_itself(recorder):
    with start_span_or_root(
        operation="api.request", trace_type="api_request", component="api"
    ):
        before = len(recorder.commands)
        with suppress_observability():
            with start_span_or_root(
                operation="database.transaction", trace_type="api_request", component="database"
            ):
                pass
        assert len(recorder.commands) == before


def test_duration_uses_monotonic_clock(recorder, monkeypatch):
    ticks = iter([1_000_000_000, 1_250_000_000])
    monkeypatch.setattr("backend.app.observability.recorder.time.perf_counter_ns", lambda: next(ticks))
    handle = start_span_or_root(
        operation="retrieval.search", trace_type="retrieval", component="retrieval"
    )
    handle.end()
    terminal = _commands(recorder, "span_end")[0]
    assert terminal.payload["duration_ms"] == 250.0


def test_raw_error_message_is_not_persisted(recorder):
    secret = "private-query-value"
    handle = start_span_or_root(
        operation="provider.generate", trace_type="analysis", component="provider"
    )
    handle.end(status="error", error=RuntimeError(secret), error_code="provider_failed")
    payload = _commands(recorder, "span_end")[0].payload
    assert secret not in str(payload)
    assert payload["error_message_template"] == "operation_failed"


def test_hmac_key_id_recorded_without_key():
    hasher = HMACHasher(key_id="key-v2", key=b"not-persisted")
    recorder = InMemoryRecorder(redactor=Redactor(hasher))
    with recorder.start_span(
        operation="api.request", trace_type="api_request", component="api",
        parent_context=None, attributes={}
    ):
        pass
    payload = _commands(recorder, "trace_start")[0].payload
    assert payload["hash_key_id"] == "key-v2"
    assert b"not-persisted" not in str(payload).encode()


def test_content_payload_is_rejected():
    with pytest.raises(ValidationError):
        TelemetryCommand(
            command_id="bad", command_type="span_event", trace_id="1" * 32,
            span_id="2" * 16, lifecycle_sequence=2, occurred_at=datetime.now(UTC),
            payload={"prompt": "do not persist"},
        )


def test_metadata_diagnostic_and_otlp_sampling_are_distinct():
    sampler = DeterministicSampler(metadata_enabled=True, diagnostic_rate=0, otlp_rate=1)
    decision = sampler.decide("1" * 32, "retrieval")
    assert decision.record_metadata is True
    assert decision.record_diagnostics is False
    assert decision.export_otlp is True


def _commands(recorder: InMemoryRecorder, kind: str):
    return [item for item in recorder.commands if item.command_type == kind]
