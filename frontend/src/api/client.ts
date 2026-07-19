import type {
  AnalysisResult,
  GlobalLibraryDetailResponse,
  GlobalLibraryListResponse,
  GlobalLibraryStats,
  LLMPublicConfig,
  ProviderPublicSettings,
  ProviderSettingsPayload,
  ProviderSettingsResponse,
  ProviderTestResponse,
  ProviderValidateResponse,
  TaskProgress,
  TaskSummary
} from "../types/analysis";
import { v2ProjectPath, v2Request, v2WorkspacePath } from "./v2Client";

export type CreateTaskPayload = {
  zip_path: string;
  output_root?: string;
  library_db_path?: string | null;
  paper_pdf_path?: string | null;
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

export function createTaskByPathAsync(payload: CreateTaskPayload): Promise<TaskProgress> {
  void payload;
  return Promise.reject(new Error("server_path_analysis_disabled"));
}

export function createTaskByUploadAsync(formData: FormData): Promise<TaskProgress> {
  void formData;
  return Promise.reject(new Error("legacy_upload_analysis_disabled"));
}

export function listTasks(): Promise<{ tasks: TaskSummary[] }> {
  return Promise.reject(new Error("legacy_task_listing_disabled"));
}

export function getTaskResult(taskId: string): Promise<AnalysisResult> {
  void taskId;
  return Promise.reject(new Error("legacy_task_result_disabled"));
}

export function getTaskProgress(taskId: string): Promise<TaskProgress> {
  void taskId;
  return Promise.reject(new Error("legacy_task_progress_disabled"));
}

export function getLLMPublicConfig(): Promise<LLMPublicConfig> {
  return v2Request<LLMPublicConfig>("/runtime/public-config");
}

export function getProviderSettings(): Promise<ProviderSettingsResponse> {
  return v2Request<ProviderSettingsResponse>(v2WorkspacePath("/settings/providers"));
}

export function saveProviderSettings(providerId: string, payload: ProviderSettingsPayload): Promise<ProviderPublicSettings> {
  return v2Request<ProviderPublicSettings>(v2WorkspacePath(`/settings/providers/${encodeURIComponent(providerId)}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function deleteProviderApiKey(providerId: string, expected_revision: number): Promise<ProviderPublicSettings> {
  return v2Request<ProviderPublicSettings>(v2WorkspacePath(`/settings/providers/${encodeURIComponent(providerId)}/api-key`), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision })
  });
}

export function validateProviderSettings(providerId: string, payload: Partial<ProviderSettingsPayload>): Promise<ProviderValidateResponse> {
  return v2Request<ProviderValidateResponse>(v2WorkspacePath(`/settings/providers/${encodeURIComponent(providerId)}/validate`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function testProviderSettings(providerId: string, confirmCost: boolean): Promise<ProviderTestResponse> {
  return v2Request<ProviderTestResponse>(v2WorkspacePath(`/settings/providers/${encodeURIComponent(providerId)}/test`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_cost: confirmCost })
  });
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
  return v2Request<GlobalLibraryListResponse>(withParams(v2ProjectPath("/library/functions"), params));
}

export function getGlobalLibraryFunction(canonicalName: string): Promise<GlobalLibraryDetailResponse> {
  return v2Request<GlobalLibraryDetailResponse>(
    v2ProjectPath(`/library/functions/${encodeURIComponent(canonicalName)}`)
  );
}

export function getGlobalLibraryStats(): Promise<GlobalLibraryStats> {
  return v2Request<GlobalLibraryStats>(v2ProjectPath("/library/stats"));
}

export function getLowConfidenceFunctions(limit = 50): Promise<{ items: GlobalLibraryListResponse["items"] }> {
  return v2Request<{ items: GlobalLibraryListResponse["items"] }>(
    withParams(v2ProjectPath("/library/functions/low-confidence"), { limit })
  );
}
