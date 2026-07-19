import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EvaluationDashboard } from "../features/evaluation/EvaluationDashboard";

afterEach(() => vi.restoreAllMocks());

test("shows evaluation runs, bad cases, and pending alignment benchmark", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/evaluations/runs") ? { items: [{ run_id: "run-1", dataset_version_id: "dataset-v1", subject_id: "subject-1", mode: "deterministic_fixture", status: "completed", complete: true, incomplete_reason_codes: [], case_counts: { total: 6, completed: 6 }, created_at: new Date().toISOString() }] }
      : url.includes("/evaluation/datasets") ? { items: [{ dataset_id: "dataset", name: "Regression", description: "", component_scope: ["retrieval"], status: "active" }] }
      : url.includes("/evaluations/baselines") ? { items: [] }
      : url.includes("/evaluations/comparisons") ? { items: [] }
      : { items: [{ bad_case_id: "bad-1", component: "retrieval", symptom: "empty_result", status: "open", severity: "high", occurrence_count: 2 }] };
    return { ok: true, json: async () => body } as Response;
  }));
  render(<EvaluationDashboard onClose={() => undefined} />);
  await waitFor(() => expect(screen.getByText("deterministic_fixture")).toBeInTheDocument());
  expect(screen.getByText("empty_result")).toBeInTheDocument();
  expect(screen.getByText(/ALIGNMENT_BENCHMARK_PENDING/)).toBeInTheDocument();
});
