import type { SpanRecord, TraceDetail, TraceEvent, TraceRecord } from "./types";

async function readJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = body?.error?.error_code;
    throw new Error(code === "observability_api_disabled" ? "Trace API 默认关闭，请由本地管理员显式启用。" : code || "Trace API 请求失败");
  }
  return body as T;
}

export async function listTraces(filters: { traceType?: string; status?: string } = {}) {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.traceType) query.set("trace_type", filters.traceType);
  if (filters.status) query.set("status", filters.status);
  return readJson<{ items: TraceRecord[]; next_cursor: number | null }>(`/observability/traces?${query}`);
}

export function getTrace(traceId: string) {
  return readJson<TraceDetail>(`/observability/traces/${encodeURIComponent(traceId)}`);
}

export function getTraceSpans(traceId: string) {
  return readJson<{ items: SpanRecord[] }>(`/observability/traces/${encodeURIComponent(traceId)}/spans?limit=2000`);
}

export function getTraceEvents(traceId: string) {
  return readJson<{ items: TraceEvent[] }>(`/observability/traces/${encodeURIComponent(traceId)}/events?limit=500`);
}

export function traceEventStreamUrl(traceId: string) {
  return `/observability/traces/${encodeURIComponent(traceId)}/events/stream`;
}
