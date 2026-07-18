export type TraceCompleteness = "complete" | "partial" | "unknown";

export type TraceRecord = {
  trace_id: string;
  trace_type: string;
  root_span_id: string;
  run_id?: string | null;
  task_id?: string | null;
  repo_id?: string | null;
  index_version_id?: string | null;
  status: string;
  started_at: string;
  ended_at?: string | null;
  duration_ms?: number | null;
  completeness: TraceCompleteness;
  integrity_flags: string[];
  dropped_record_count: number;
  attribute_registry_version: string;
  operation_taxonomy_version: string;
  recording_mode: string;
  attributes: Record<string, unknown>;
  error_code?: string | null;
};

export type SpanRecord = {
  trace_id: string;
  span_id: string;
  parent_span_id?: string | null;
  name: string;
  component: string;
  kind: string;
  status: string;
  started_at: string;
  ended_at?: string | null;
  duration_ms?: number | null;
  duration_estimated: boolean;
  attributes: Record<string, unknown>;
  error_code?: string | null;
  exception_type?: string | null;
  error_message_template?: string | null;
};

export type TraceEvent = {
  event_id: string;
  trace_id: string;
  span_id: string;
  producer_sequence?: number | null;
  stream_sequence?: number | null;
  name: string;
  severity: string;
  occurred_at: string;
  attributes: Record<string, unknown>;
};

export type SpanLink = {
  link_id: string;
  span_id: string;
  linked_trace_id: string;
  linked_span_id?: string | null;
  relation: string;
};

export type ArtifactRef = {
  ref_id: string;
  span_id: string;
  artifact_type: string;
  artifact_id: string;
  role: string;
};

export type TraceDetail = {
  trace: TraceRecord;
  links: SpanLink[];
  artifacts: ArtifactRef[];
};
