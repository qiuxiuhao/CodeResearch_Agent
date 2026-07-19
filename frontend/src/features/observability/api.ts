import type { SpanRecord, TraceDetail, TraceEvent, TraceRecord } from "./types";
import { v2ProjectPath, v2Request } from "../../api/v2Client";

function readTraceJson<T>(suffix: string): Promise<T> {
  return v2Request<T>(v2ProjectPath(`/observability${suffix}`)).catch((exc) => {
    const message = exc instanceof Error ? exc.message : "Trace API 请求失败";
    throw new Error(message === "observability_api_disabled" ? "Trace API 默认关闭，请由本地管理员显式启用。" : message);
  });
}

export async function listTraces(filters: { traceType?: string; status?: string } = {}) {
  const query = new URLSearchParams({ limit: "100" });
  if (filters.traceType) query.set("trace_type", filters.traceType);
  if (filters.status) query.set("status", filters.status);
  return readTraceJson<{ items: TraceRecord[]; next_cursor: number | null }>(`/traces?${query}`);
}

export function getTrace(traceId: string) {
  return readTraceJson<TraceDetail>(`/traces/${encodeURIComponent(traceId)}`);
}

export function getTraceSpans(traceId: string) {
  return readTraceJson<{ items: SpanRecord[] }>(`/traces/${encodeURIComponent(traceId)}/spans?limit=2000`);
}

export function getTraceEvents(traceId: string, afterSequence = 0) {
  const query = new URLSearchParams({ limit: "500", after_sequence: String(afterSequence) });
  return readTraceJson<{ items: TraceEvent[] }>(`/traces/${encodeURIComponent(traceId)}/events?${query}`);
}
