export type PlatformHealth = {
  status: "ok";
  profile: "local" | "team";
  api_contract_version: "2";
};

export type JobStatus =
  | "queued"
  | "dispatching"
  | "dispatched"
  | "running"
  | "retry_wait"
  | "cancelling"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "dead";

export type JobView = {
  job_id: string;
  workspace_id: string;
  project_id: string | null;
  job_type: string;
  status: JobStatus;
  current_attempt_number: number;
  max_attempts: number;
  error_code: string | null;
  updated_at: string;
};

export type WorkspaceView = {
  workspace_id: string;
  name: string;
  status: string;
  role: string;
};

export type ProjectView = {
  project_id: string;
  workspace_id: string;
  name: string;
  status: string;
  role: string | null;
};

export type AttemptView = {
  attempt_id: string;
  attempt_number: number;
  status: string;
  worker_id_hash: string | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type ArtifactView = {
  artifact_id: string;
  workspace_id: string;
  project_id: string;
  kind: string;
  status: string;
  content_hash: string;
  size_bytes: number;
  media_type: string;
  created_at: string;
};

export type LocalSessionView = {
  access_token: string;
  token_type: "bearer";
  session_id: string;
  workspace_id: string;
  project_id: string;
};

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let activeWorkspaceId: string | null = null;
let activeScope: {workspaceId: string; projectId: string} | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setActiveScope(workspaceId: string, projectId: string): void {
  activeWorkspaceId = workspaceId || null;
  activeScope = workspaceId && projectId ? {workspaceId, projectId} : null;
}

export function v2WorkspacePath(suffix: string): string {
  if (!activeWorkspaceId) throw new Error("workspace_scope_required");
  return `/workspaces/${encodeURIComponent(activeWorkspaceId)}${suffix}`;
}

export function v2ProjectPath(suffix: string): string {
  if (!activeScope) throw new Error("project_scope_required");
  const {workspaceId, projectId} = activeScope;
  return `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export async function v2Request<T>(
  path: string, init: RequestInit = {}, allowRefresh = true
): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`/api/v2${path}`, {...init, headers, credentials: "include"});
  if (response.status === 401 && allowRefresh && await restoreSession()) {
    return v2Request<T>(path, init, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {detail?: {error_code?: string} | string; error?: {error_code?: string}} | null;
    const detail = body?.detail;
    throw new Error(
      (typeof detail === "string" ? detail : detail?.error_code)
        ?? body?.error?.error_code
        ?? `request_failed_${response.status}`
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getPlatformHealth(): Promise<PlatformHealth> {
  return v2Request<PlatformHealth>("/health");
}

export async function bootstrapOwner(
  bootstrapToken: string, username: string, password: string
): Promise<void> {
  await v2Request<{user_id: string}>("/auth/bootstrap", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Bootstrap-Token": bootstrapToken,
    },
    body: JSON.stringify({username, password}),
  }, false);
}

export async function startLocalSession(): Promise<LocalSessionView> {
  const response = await v2Request<LocalSessionView>("/auth/local-session", {
    method: "POST",
  }, false);
  setAccessToken(response.access_token);
  return response;
}

export function formatV2Error(reason: unknown): string {
  const code = reason instanceof Error ? reason.message : String(reason || "request_failed");
  return {
    authentication_failed: "账号或密码错误。",
    authentication_required: "请先登录。",
    login_rate_limited: "登录失败次数过多，请稍后再试。",
    bootstrap_invalid: "初始化令牌无效或已使用。",
    invalid_registration: "账号至少 3 位，密码至少 12 位。",
    invalid_password: "新密码至少 12 位。",
    csrf_required: "登录会话已失效，请重新登录。",
    local_session_unavailable: "当前服务不支持免登录 Local 会话。",
    request_failed_400: "请求参数不正确。",
    request_failed_401: "账号或密码错误。",
    request_failed_403: "没有权限执行该操作。",
    request_failed_405: "当前后端还未加载免登录接口，请停止并重新启动 cra serve。",
    request_failed_422: "请求内容不符合要求。",
  }[code] ?? code;
}

export async function login(username: string, password: string): Promise<void> {
  const response = await v2Request<{access_token: string}>("/auth/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username, password}),
  }, false);
  setAccessToken(response.access_token);
}

export function restoreSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = refreshSession().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

async function refreshSession(): Promise<boolean> {
  const csrf = readCookie("cra_csrf");
  if (!csrf) {
    setAccessToken(null);
    return false;
  }
  const response = await fetch("/api/v2/auth/refresh", {
    method: "POST",
    credentials: "include",
    headers: {"X-CSRF-Token": csrf},
  });
  if (!response.ok) {
    setAccessToken(null);
    return false;
  }
  const body = await response.json() as {access_token: string};
  setAccessToken(body.access_token);
  return true;
}

function readCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return null;
}

export function listWorkspaces(): Promise<{items: WorkspaceView[]}> {
  return v2Request<{items: WorkspaceView[]}>("/workspaces");
}

export function listProjects(workspaceId: string): Promise<{items: ProjectView[]}> {
  return v2Request<{items: ProjectView[]}>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects`
  );
}

export function listJobs(workspaceId: string, projectId: string): Promise<{items: JobView[]}> {
  return v2Request<{items: JobView[]}>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/jobs`
  );
}

export function listArtifacts(
  workspaceId: string, projectId: string
): Promise<{items: ArtifactView[]}> {
  return v2Request<{items: ArtifactView[]}>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/artifacts`
  );
}

export async function uploadArtifact(
  workspaceId: string, projectId: string, file: File
): Promise<ArtifactView> {
  const form = new FormData();
  form.append("artifact", file);
  return v2Request<ArtifactView>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/artifacts`,
    {method: "POST", body: form}
  );
}

export function submitJob(
  workspaceId: string,
  projectId: string,
  jobType: string,
  payload: Record<string, unknown>,
  idempotencyKey: string,
): Promise<{job_id: string; attempt_id: string; domain_run_id: string}> {
  return v2Request(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/jobs`,
    {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({job_type: jobType, payload, idempotency_key: idempotencyKey}),
    }
  );
}

export async function downloadArtifact(
  workspaceId: string, projectId: string, artifactId: string
): Promise<Blob> {
  const path =
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}` +
    `/artifacts/${encodeURIComponent(artifactId)}/content`;
  const headers = new Headers();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`/api/v2${path}`, {headers, credentials: "include"});
  if (!response.ok) throw new Error(`request_failed_${response.status}`);
  return response.blob();
}

export function listAttempts(
  workspaceId: string, projectId: string, jobId: string
): Promise<{items: AttemptView[]}> {
  return v2Request<{items: AttemptView[]}>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}` +
      `/jobs/${encodeURIComponent(jobId)}/attempts`
  );
}

export function cancelJob(workspaceId: string, projectId: string, jobId: string): Promise<JobView> {
  return v2Request<JobView>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}` +
      `/jobs/${encodeURIComponent(jobId)}/cancel`,
    {method: "POST"}
  );
}

export function retryJob(
  workspaceId: string, projectId: string, jobId: string
): Promise<{job_id: string; attempt_id: string; domain_run_id: string}> {
  return v2Request(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}` +
      `/jobs/${encodeURIComponent(jobId)}/retry`,
    {method: "POST"}
  );
}

export function getJob(
  workspaceId: string,
  projectId: string,
  jobId: string
): Promise<JobView> {
  return v2Request<JobView>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}`
  );
}

export function getAnalysisJobResult<T>(
  workspaceId: string, projectId: string, jobId: string
): Promise<T> {
  return v2Request<T>(
    `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}` +
      `/analysis-jobs/${encodeURIComponent(jobId)}/result`
  );
}

export async function fetchActiveAnalysisAsset(jobId: string, suffix: string): Promise<Blob> {
  if (!activeScope) throw new Error("project_scope_required");
  const {workspaceId, projectId} = activeScope;
  const headers = new Headers();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const url =
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}` +
    `/projects/${encodeURIComponent(projectId)}/analysis-jobs/${encodeURIComponent(jobId)}/${suffix}`;
  let response = await fetch(url, {headers, credentials: "include"});
  if (response.status === 401 && await restoreSession()) {
    const retryHeaders = new Headers();
    if (accessToken) retryHeaders.set("Authorization", `Bearer ${accessToken}`);
    response = await fetch(url, {headers: retryHeaders, credentials: "include"});
  }
  if (!response.ok) throw new Error(`request_failed_${response.status}`);
  return response.blob();
}
