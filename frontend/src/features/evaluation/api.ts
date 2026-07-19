import type { BadCase, BaselineBinding, Comparison, EvaluationDataset, EvaluationRun } from "./types";

async function readJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = body?.error?.error_code;
    throw new Error(code === "evaluation_api_disabled" ? "Evaluation API 默认关闭，请由本地管理员显式启用。" : code || "Evaluation API 请求失败");
  }
  return body as T;
}

export function listEvaluationRuns() {
  return readJson<{ items: EvaluationRun[] }>("/evaluations/runs?limit=100");
}

export function listEvaluationDatasets() {
  return readJson<{ items: EvaluationDataset[] }>("/evaluation/datasets");
}

export function listBaselines() {
  return readJson<{ items: BaselineBinding[] }>("/evaluations/baselines");
}

export function listComparisons() {
  return readJson<{ items: Comparison[] }>("/evaluations/comparisons?limit=100");
}

export function listBadCases(status = "") {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return readJson<{ items: BadCase[] }>(`/bad-cases${query}`);
}
