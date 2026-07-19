from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


SCHEMA_VERSION = "1"
TRACE_ID_PATTERN = r"^[0-9a-f]{32}$"
SPAN_ID_PATTERN = r"^[0-9a-f]{16}$"
MAX_ATTRIBUTES = 64
MAX_ATTRIBUTE_KEY = 128
MAX_ATTRIBUTE_STRING = 1_024
MAX_EVENT_BYTES = 8 * 1_024
MAX_ATTRIBUTES_BYTES = 16 * 1_024
MAX_COMMAND_PAYLOAD_BYTES = 32 * 1_024

TraceType = Literal[
    "api_request", "analysis", "indexing", "retrieval", "research_agent", "alignment",
    "evaluation",
]
SpanComponent = Literal[
    "api", "analysis_graph", "indexing", "retrieval", "agent", "alignment",
    "provider", "tool", "database", "checkpoint", "cache", "evaluation",
]
RecordingMode = Literal["none", "metadata", "diagnostic_metadata"]
TraceStatus = Literal["running", "completed", "partial", "failed", "cancelled", "abandoned"]
SpanStatus = Literal["running", "ok", "error", "cancelled", "abandoned"]
Completeness = Literal["complete", "partial", "unknown"]
IntegrityFlag = Literal[
    "missing_root_start", "missing_root_end", "missing_span_start", "missing_span_end",
    "sequence_gap", "queue_drop", "store_failure", "process_crash", "orphan_span",
    "export_incomplete",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("attributes", check_fields=False)
    @classmethod
    def validate_attributes(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return validate_bounded_attributes(value)

    @field_validator(
        "started_at", "ended_at", "occurred_at", "recorded_at", "created_at",
        "updated_at", "next_attempt_at", check_fields=False,
    )
    @classmethod
    def require_utc_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observability timestamps must be timezone-aware")
        return value.astimezone(UTC)


class RecordingDecision(StrictModel):
    record_metadata: bool = True
    record_diagnostics: bool = False
    export_otlp: bool = False
    reason_codes: list[str] = Field(default_factory=list, max_length=20)


class TraceContext(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str = Field(pattern=SPAN_ID_PATTERN)
    trace_flags: int = Field(default=0, ge=0, le=255)
    tracestate: str | None = Field(default=None, max_length=512)
    request_id: str | None = Field(default=None, max_length=128)
    trace_type: TraceType
    run_id: str | None = Field(default=None, max_length=256)
    task_id: str | None = Field(default=None, max_length=256)
    repo_id: str | None = Field(default=None, max_length=256)
    index_version_id: str | None = Field(default=None, max_length=256)
    caller_scope_hash: str | None = Field(default=None, max_length=256)
    recording: RecordingDecision = Field(default_factory=RecordingDecision)


class TraceRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    trace_type: TraceType
    root_span_id: str = Field(pattern=SPAN_ID_PATTERN)
    request_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    repo_id: str | None = None
    index_version_id: str | None = None
    caller_scope_hash: str | None = None
    status: TraceStatus
    lifecycle_version: int = Field(default=1, ge=1)
    last_command_id: str | None = None
    completion_status: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    duration_estimated: bool = False
    recording_mode: RecordingMode = "metadata"
    diagnostic_sampled: bool = False
    otlp_sampled: bool = False
    completeness: Completeness = "unknown"
    integrity_flags: list[IntegrityFlag] = Field(default_factory=list)
    attribute_registry_version: str = "cra-attributes-v1"
    operation_taxonomy_version: str = "cra-operations-v1"
    semantic_convention_version: str | None = None
    hash_key_id: str | None = None
    hash_algorithm: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    error_code: str | None = None
    span_count: int = Field(default=0, ge=0)
    event_count: int = Field(default=0, ge=0)
    dropped_record_count: int = Field(default=0, ge=0)
    retention_hold: bool = False


class SpanRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str = Field(pattern=SPAN_ID_PATTERN)
    parent_span_id: str | None = Field(default=None, pattern=SPAN_ID_PATTERN)
    name: str = Field(min_length=1, max_length=160)
    component: SpanComponent
    kind: Literal["internal", "server", "client", "producer", "consumer"] = "internal"
    status: SpanStatus
    lifecycle_version: int = Field(default=1, ge=1)
    last_command_id: str | None = None
    completion_status: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    duration_estimated: bool = False
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    error_code: str | None = None
    exception_type: str | None = Field(default=None, max_length=256)
    error_message_template: str | None = Field(default=None, max_length=512)
    error_message_hash: str | None = Field(default=None, max_length=256)
    dropped_attribute_count: int = Field(default=0, ge=0)
    dropped_event_count: int = Field(default=0, ge=0)


class TraceEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str = Field(pattern=SPAN_ID_PATTERN)
    producer_sequence: int | None = Field(default=None, ge=0)
    stream_sequence: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=160)
    severity: Literal["debug", "info", "warning", "error"] = "info"
    occurred_at: datetime
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    size_bytes: int = Field(default=0, ge=0, le=MAX_EVENT_BYTES)


class SpanLink(StrictModel):
    schema_version: str = SCHEMA_VERSION
    link_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str = Field(pattern=SPAN_ID_PATTERN)
    linked_trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    linked_span_id: str | None = Field(default=None, pattern=SPAN_ID_PATTERN)
    relation: Literal[
        "queued_from", "resume_of", "retry_of", "reused_from", "continued_from",
        "checkpoint_of", "linked_from_remote", "evaluates", "replay_of",
    ]
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class TraceArtifactRef(StrictModel):
    schema_version: str = SCHEMA_VERSION
    ref_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str = Field(pattern=SPAN_ID_PATTERN)
    artifact_type: Literal[
        "run", "task", "checkpoint", "manifest", "entity", "chunk", "edge",
        "evidence", "decision", "generation", "report",
    ]
    artifact_id: str = Field(min_length=1, max_length=512)
    content_hash: str | None = Field(default=None, max_length=256)
    repo_id: str | None = Field(default=None, max_length=256)
    index_version_id: str | None = Field(default=None, max_length=256)
    role: str = Field(min_length=1, max_length=128)


class MetricSnapshot(StrictModel):
    schema_version: str = SCHEMA_VERSION
    snapshot_id: str
    trace_id: str | None = Field(default=None, pattern=TRACE_ID_PATTERN)
    span_id: str | None = Field(default=None, pattern=SPAN_ID_PATTERN)
    metric_name: str = Field(min_length=1, max_length=160)
    metric_type: Literal["counter", "gauge", "histogram"]
    value: float | None = None
    count: int | None = Field(default=None, ge=0)
    sum: float | None = None
    bucket_counts: list[int] = Field(default_factory=list, max_length=100)
    explicit_bounds: list[float] = Field(default_factory=list, max_length=100)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    telemetry_complete: bool = True
    recorded_at: datetime


class TracePersistenceStatus(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    status: Literal["queued", "persisting", "persisted", "failed", "dropped"]
    attempt_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    updated_at: datetime


class TraceExportJob(StrictModel):
    schema_version: str = SCHEMA_VERSION
    export_job_id: str
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    exporter: Literal["otlp_http"] = "otlp_http"
    status: Literal["queued", "exporting", "exported", "failed", "dropped"]
    attempt_count: int = Field(default=0, ge=0)
    next_attempt_at: datetime | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ReplayManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    run_id: str | None = Field(default=None, max_length=256)
    repo_id: str | None = Field(default=None, max_length=256)
    index_version_id: str | None = Field(default=None, max_length=256)
    graph_version: str | None = Field(default=None, max_length=256)
    model_profile_id: str | None = Field(default=None, max_length=256)
    artifact_ref_ids: list[str] = Field(default_factory=list, max_length=200)
    readiness: Literal["replay_ready", "not_ready"]
    reason_codes: list[str] = Field(default_factory=list, max_length=50)
    execution_requested: Literal[False] = False
    generated_at: datetime


class TelemetryCommand(StrictModel):
    schema_version: str = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    command_type: Literal[
        "trace_start", "span_start", "span_event", "span_link", "artifact_ref",
        "span_end", "trace_end",
    ]
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str | None = Field(default=None, pattern=SPAN_ID_PATTERN)
    lifecycle_sequence: int = Field(ge=1)
    occurred_at: datetime
    payload: dict[str, JsonValue]

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_COMMAND_PAYLOAD_BYTES:
            raise ValueError("telemetry command payload is too large")
        _reject_content_keys(value)
        return value

    @model_validator(mode="after")
    def validate_span_identity(self) -> "TelemetryCommand":
        if self.command_type != "trace_start" and self.span_id is None:
            raise ValueError("span_id is required for non-trace-start commands")
        return self


class CallerIdentity(StrictModel):
    identity_type: Literal["local_admin", "authenticated", "anonymous"]
    subject: str = Field(min_length=1, max_length=256)
    repository_ids: list[str] = Field(default_factory=list, max_length=500)


class TraceFilter(StrictModel):
    start: datetime | None = None
    end: datetime | None = None
    status: TraceStatus | None = None
    trace_type: TraceType | None = None
    component: SpanComponent | None = None
    operation: str | None = Field(default=None, max_length=160)
    repo_id: str | None = Field(default=None, max_length=256)
    index_version_id: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=256)
    error_code: str | None = Field(default=None, max_length=160)
    min_duration_ms: float | None = Field(default=None, ge=0)
    max_duration_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "TraceFilter":
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must be before end")
        if (
            self.min_duration_ms is not None
            and self.max_duration_ms is not None
            and self.min_duration_ms > self.max_duration_ms
        ):
            raise ValueError("min_duration_ms must not exceed max_duration_ms")
        return self


class AttributeDefinition(StrictModel):
    key: str = Field(min_length=1, max_length=MAX_ATTRIBUTE_KEY)
    value_type: Literal["string", "integer", "number", "boolean", "string_list"]
    cardinality: Literal["low", "bounded", "high"]
    content_policy: Literal["metadata", "diagnostic_metadata", "forbidden"]
    metric_label_allowed: bool
    introduced_in: str
    deprecated_in: str | None = None
    removed_in: str | None = None
    replacement_key: str | None = None
    value_schema_version: str = "1"


def validate_bounded_attributes(attributes: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if len(attributes) > MAX_ATTRIBUTES:
        raise ValueError(f"at most {MAX_ATTRIBUTES} attributes are allowed")
    for key, value in attributes.items():
        if len(key) > MAX_ATTRIBUTE_KEY:
            raise ValueError("attribute key is too long")
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_ATTRIBUTE_STRING:
            raise ValueError("attribute string is too large")
    if len(json.dumps(attributes, ensure_ascii=False).encode("utf-8")) > MAX_ATTRIBUTES_BYTES:
        raise ValueError("attribute payload is too large")
    return attributes


_FORBIDDEN_CONTENT_KEYS = {
    "authorization", "cookie", "secret", "password", "connection_string",
    "prompt", "query", "response", "source_code", "paper_text", "checkpoint_blob",
    "research_state", "request_body", "response_body", "error_message",
}


def _reject_content_keys(value: JsonValue) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _FORBIDDEN_CONTENT_KEYS:
                raise ValueError(f"content field is forbidden in telemetry: {key}")
            _reject_content_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_content_keys(child)
