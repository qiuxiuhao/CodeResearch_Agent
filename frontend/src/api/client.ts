import type {
  AnalysisResult,
  GlobalLibraryDetailResponse,
  GlobalLibraryListResponse,
  GlobalLibraryStats,
  LLMPublicConfig,
  AnalysisMode,
  ProviderPublicSettings,
  ProviderSettingsPayload,
  ProviderSettingsResponse,
  ProviderTestResponse,
  ProviderValidateResponse,
  TaskProgress,
  TaskSummary
} from "../types/analysis";

export type CreateTaskPayload = {
  zip_path: string;
  output_root?: string;
  library_db_path?: string | null;
  paper_pdf_path?: string | null;
  analysis_mode?: AnalysisMode;
  external_model_consent?: boolean;
  text_llm_enabled?: boolean;
  teaching_narrative_llm_enabled?: boolean;
  vision_vlm_enabled?: boolean;
  external_text_consent?: boolean;
  external_vision_consent?: boolean;
  teaching_diagrams_enabled?: boolean;
  image_generation_enabled?: boolean;
  external_image_consent?: boolean;
  teaching_review_vlm_enabled?: boolean;
  external_teaching_review_consent?: boolean;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const contentType = response.headers?.get("content-type") ?? "";
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
  if (contentType && !contentType.includes("application/json")) {
    const preview = (await response.text()).slice(0, 80).replace(/\s+/g, " ");
    throw new Error(`接口 ${url} 没有返回 JSON，请确认后端服务和 Vite proxy 已启动。返回内容：${preview}`);
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

export function createTaskByPathAsync(payload: CreateTaskPayload): Promise<TaskProgress> {
  return requestJson<TaskProgress>("/analysis/tasks/async", {
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

export function createTaskByUploadAsync(formData: FormData): Promise<TaskProgress> {
  return requestJson<TaskProgress>("/analysis/tasks/upload/async", {
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

export function getTaskProgress(taskId: string): Promise<TaskProgress> {
  return requestJson<TaskProgress>(`/analysis/tasks/${encodeURIComponent(taskId)}/progress`);
}

export function getTaskReport(taskId: string): Promise<{ task_id: string; report_md: string }> {
  return requestJson<{ task_id: string; report_md: string }>(`/analysis/tasks/${encodeURIComponent(taskId)}/report`);
}

export function getLLMPublicConfig(): Promise<LLMPublicConfig> {
  return requestJson<LLMPublicConfig>("/llm/public-config");
}

export function getProviderSettings(): Promise<ProviderSettingsResponse> {
  return requestJson<ProviderSettingsResponse>("/settings/providers");
}

export function saveProviderSettings(providerId: string, payload: ProviderSettingsPayload): Promise<ProviderPublicSettings> {
  return requestJson<ProviderPublicSettings>(`/settings/providers/${encodeURIComponent(providerId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function deleteProviderApiKey(providerId: string, expected_revision: number): Promise<ProviderPublicSettings> {
  return requestJson<ProviderPublicSettings>(`/settings/providers/${encodeURIComponent(providerId)}/api-key`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision })
  });
}

export function validateProviderSettings(providerId: string, payload: Partial<ProviderSettingsPayload>): Promise<ProviderValidateResponse> {
  return requestJson<ProviderValidateResponse>(`/settings/providers/${encodeURIComponent(providerId)}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function testProviderSettings(providerId: string, confirmCost: boolean): Promise<ProviderTestResponse> {
  return requestJson<ProviderTestResponse>(`/settings/providers/${encodeURIComponent(providerId)}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_cost: confirmCost })
  });
}

export function figurePreviewUrl(taskId: string, figureId: string): string {
  return `/analysis/tasks/${encodeURIComponent(taskId)}/figures/${encodeURIComponent(figureId)}/preview`;
}

export function figureAssetUrl(taskId: string, figureId: string, assetId: string): string {
  return `/analysis/tasks/${encodeURIComponent(taskId)}/figures/${encodeURIComponent(figureId)}/assets/${encodeURIComponent(assetId)}`;
}

export function teachingDiagramAssetUrl(taskId: string, diagramId: string, assetName: "blueprint.svg" | "blueprint.png" | "final.png" | "raw.png"): string {
  return `/analysis/tasks/${encodeURIComponent(taskId)}/teaching-diagrams/${encodeURIComponent(diagramId)}/${assetName}`;
}

export type GlobalLibraryQuery = {
  query?: string;
  package_name?: string;
  category?: string;
  confidence?: string;
  limit?: number;
  offset?: number;
  sort?: string;
  library_db_path?: string;
};

function withParams(path: string, params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const queryString = search.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export function listGlobalLibraryFunctions(params: GlobalLibraryQuery = {}): Promise<GlobalLibraryListResponse> {
  return requestJson<GlobalLibraryListResponse>(withParams("/library/functions", params));
}

export function getGlobalLibraryFunction(canonicalName: string): Promise<GlobalLibraryDetailResponse> {
  return requestJson<GlobalLibraryDetailResponse>(`/library/functions/${encodeURIComponent(canonicalName)}`);
}

export function getGlobalLibraryStats(): Promise<GlobalLibraryStats> {
  return requestJson<GlobalLibraryStats>("/library/stats");
}

export function getLowConfidenceFunctions(limit = 50): Promise<{ items: GlobalLibraryListResponse["items"] }> {
  return requestJson<{ items: GlobalLibraryListResponse["items"] }>(withParams("/library/functions/low-confidence", { limit }));
}
