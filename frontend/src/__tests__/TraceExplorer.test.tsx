import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { TraceExplorer } from "../features/observability/TraceExplorer";
import { setActiveScope } from "../api/v2Client";

const trace = {
  trace_id: "1".repeat(32), trace_type: "research_agent", root_span_id: "2".repeat(16),
  status: "partial", started_at: "2026-07-18T00:00:00Z", ended_at: "2026-07-18T00:00:01Z",
  duration_ms: 1000, completeness: "partial", integrity_flags: ["queue_drop"],
  dropped_record_count: 2, attribute_registry_version: "cra-attributes-v1",
  operation_taxonomy_version: "cra-operations-v1", recording_mode: "metadata", attributes: {}
};

test("ui exposes incomplete trace instead of drawing it as complete", async () => {
  setActiveScope("workspace-a", "project-a");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.endsWith("/spans?limit=2000")
      ? { items: [{ trace_id: trace.trace_id, span_id: trace.root_span_id, parent_span_id: null, name: "agent.run", component: "agent", kind: "internal", status: "ok", started_at: trace.started_at, ended_at: trace.ended_at, duration_ms: 1000, duration_estimated: false, attributes: {} }] }
      : url.includes("/events?") ? { items: [] }
      : url.includes(`/traces/${trace.trace_id}`) ? { trace, links: [], artifacts: [] }
      : { items: [trace], next_cursor: null };
    return { ok: true, headers: { get: () => "application/json" }, json: async () => body } as unknown as Response;
  }));
  render(<TraceExplorer onClose={() => undefined} />);
  await waitFor(() => expect(screen.getAllByText("partial telemetry").length).toBeGreaterThan(0));
  await waitFor(() => expect(screen.getByText(/此调用链不完整/)).toHaveTextContent("queue_drop"));
  expect(screen.getByText("agent.run")).toBeInTheDocument();
  vi.unstubAllGlobals();
});
