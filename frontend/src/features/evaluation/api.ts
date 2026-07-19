import type { BadCase, BaselineBinding, Comparison, EvaluationDataset, EvaluationRun } from "./types";
import { v2ProjectPath, v2Request } from "../../api/v2Client";

function readEvaluationJson<T>(suffix: string): Promise<T> {
  return v2Request<T>(v2ProjectPath(`/evaluation${suffix}`)).catch((exc) => {
    const message = exc instanceof Error ? exc.message : "Evaluation API 请求失败";
    throw new Error(message === "evaluation_api_disabled" ? "Evaluation API 默认关闭，请由本地管理员显式启用。" : message);
  });
}

export function listEvaluationRuns() {
  return readEvaluationJson<{ items: EvaluationRun[] }>("/runs?limit=100");
}

export function listEvaluationDatasets() {
  return readEvaluationJson<{ items: EvaluationDataset[] }>("/datasets");
}

export function listBaselines() {
  return readEvaluationJson<{ items: BaselineBinding[] }>("/baselines");
}

export function listComparisons() {
  return readEvaluationJson<{ items: Comparison[] }>("/comparisons?limit=100");
}

export function listBadCases(status = "") {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return readEvaluationJson<{ items: BadCase[] }>(`/bad-cases${query}`);
}
