PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    trace_type TEXT NOT NULL,
    root_span_id TEXT NOT NULL,
    request_id TEXT,
    run_id TEXT,
    task_id TEXT,
    repo_id TEXT,
    index_version_id TEXT,
    caller_scope_hash TEXT,
    status TEXT NOT NULL,
    lifecycle_version INTEGER NOT NULL DEFAULT 1,
    last_command_id TEXT,
    completion_status TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_ms REAL,
    duration_estimated INTEGER NOT NULL DEFAULT 0,
    recording_mode TEXT NOT NULL,
    diagnostic_sampled INTEGER NOT NULL DEFAULT 0,
    otlp_sampled INTEGER NOT NULL DEFAULT 0,
    completeness TEXT NOT NULL DEFAULT 'unknown',
    integrity_flags_json TEXT NOT NULL DEFAULT '[]',
    attribute_registry_version TEXT NOT NULL,
    operation_taxonomy_version TEXT NOT NULL,
    semantic_convention_version TEXT,
    hash_key_id TEXT,
    hash_algorithm TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    span_count INTEGER NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0,
    dropped_record_count INTEGER NOT NULL DEFAULT 0,
    retention_hold INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS spans (
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    component TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    lifecycle_version INTEGER NOT NULL DEFAULT 1,
    last_command_id TEXT,
    completion_status TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_ms REAL,
    duration_estimated INTEGER NOT NULL DEFAULT 0,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    exception_type TEXT,
    error_message_template TEXT,
    error_message_hash TEXT,
    dropped_attribute_count INTEGER NOT NULL DEFAULT 0,
    dropped_event_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trace_id, span_id),
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS telemetry_commands (
    command_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_id TEXT,
    command_type TEXT NOT NULL,
    lifecycle_sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    result TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_span_terminals (
    command_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    lifecycle_sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS span_events (
    trace_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    producer_sequence INTEGER,
    stream_sequence INTEGER NOT NULL,
    name TEXT NOT NULL,
    severity TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trace_id, event_id),
    UNIQUE (trace_id, stream_sequence),
    FOREIGN KEY (trace_id, span_id) REFERENCES spans(trace_id, span_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trace_stream_sequences (
    trace_id TEXT PRIMARY KEY,
    next_sequence INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS span_links (
    link_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    linked_trace_id TEXT NOT NULL,
    linked_span_id TEXT,
    relation TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (trace_id, span_id) REFERENCES spans(trace_id, span_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trace_artifact_refs (
    ref_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    content_hash TEXT,
    repo_id TEXT,
    index_version_id TEXT,
    role TEXT NOT NULL,
    FOREIGN KEY (trace_id, span_id) REFERENCES spans(trace_id, span_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trace_metric_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    trace_id TEXT,
    span_id TEXT,
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    value REAL,
    count INTEGER,
    sum REAL,
    bucket_counts_json TEXT NOT NULL DEFAULT '[]',
    explicit_bounds_json TEXT NOT NULL DEFAULT '[]',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    telemetry_complete INTEGER NOT NULL DEFAULT 1,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_persistence_status (
    trace_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_export_jobs (
    export_job_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    exporter TEXT NOT NULL CHECK (exporter = 'otlp_http'),
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at DESC, trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_type_status ON traces(trace_type, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_repo_version ON traces(repo_id, index_version_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_error ON traces(error_code, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_spans_component_name ON spans(component, name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_stream ON span_events(trace_id, stream_sequence);

PRAGMA user_version = 1;
