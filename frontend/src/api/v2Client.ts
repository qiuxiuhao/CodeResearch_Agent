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

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export async function v2Request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`/api/v2${path}`, {...init, headers, credentials: "include"});
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {detail?: {error_code?: string}} | null;
    throw new Error(body?.detail?.error_code ?? `request_failed_${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getPlatformHealth(): Promise<PlatformHealth> {
  return v2Request<PlatformHealth>("/health");
}

export async function login(username: string, password: string): Promise<void> {
  const response = await v2Request<{access_token: string}>("/auth/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username, password}),
  });
  setAccessToken(response.access_token);
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
