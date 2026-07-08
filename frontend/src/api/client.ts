import type { AnalysisResult, TaskSummary } from "../types/analysis";

export type CreateTaskPayload = {
  zip_path: string;
  output_root?: string;
  library_db_path?: string | null;
  paper_pdf_path?: string | null;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // keep status text
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function createTaskByPath(payload: CreateTaskPayload): Promise<TaskSummary> {
  return requestJson<TaskSummary>("/analysis/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function createTaskByUpload(formData: FormData): Promise<TaskSummary> {
  return requestJson<TaskSummary>("/analysis/tasks/upload", {
    method: "POST",
    body: formData
  });
}

export function listTasks(): Promise<{ tasks: TaskSummary[] }> {
  return requestJson<{ tasks: TaskSummary[] }>("/analysis/tasks");
}

export function getTaskResult(taskId: string): Promise<AnalysisResult> {
  return requestJson<AnalysisResult>(`/analysis/tasks/${encodeURIComponent(taskId)}`);
}

export function getTaskReport(taskId: string): Promise<{ task_id: string; report_md: string }> {
  return requestJson<{ task_id: string; report_md: string }>(`/analysis/tasks/${encodeURIComponent(taskId)}/report`);
}
