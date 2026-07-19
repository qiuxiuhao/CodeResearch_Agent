import {FormEvent, useCallback, useEffect, useState} from "react";
import {
  cancelJob, getPlatformHealth, listAttempts, listJobs, listProjects, listWorkspaces,
  login, restoreSession, retryJob, type AttemptView, type JobView, type PlatformHealth,
  type ProjectView, type WorkspaceView,
} from "../../api/v2Client";

type Props = { onClose: () => void };

export function JobCenter({onClose}: Props) {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceView[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [projectId, setProjectId] = useState("");
  const [jobs, setJobs] = useState<JobView[]>([]);
  const [attempts, setAttempts] = useState<AttemptView[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");

  useEffect(() => {
    void getPlatformHealth().then(setHealth).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "platform_unavailable");
    });
    void restoreSession().then(setAuthenticated).catch(() => setAuthenticated(false));
  }, []);

  const refreshJobs = useCallback(async () => {
    if (!workspaceId || !projectId) return;
    const response = await listJobs(workspaceId, projectId);
    setJobs(response.items);
  }, [projectId, workspaceId]);

  useEffect(() => {
    if (!authenticated) return;
    void listWorkspaces().then(({items}) => {
      setWorkspaces(items);
      setWorkspaceId((current) => current || items[0]?.workspace_id || "");
    }).catch((reason: unknown) => setError(errorText(reason)));
  }, [authenticated]);

  useEffect(() => {
    if (!workspaceId) return;
    void listProjects(workspaceId).then(({items}) => {
      setProjects(items);
      setProjectId(items[0]?.project_id || "");
    }).catch((reason: unknown) => setError(errorText(reason)));
  }, [workspaceId]);

  useEffect(() => {
    if (!projectId) return;
    void refreshJobs().catch((reason: unknown) => setError(errorText(reason)));
    const timer = window.setInterval(() => {
      void refreshJobs().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [projectId, refreshJobs]);

  async function submitLogin(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await login(username, password);
      setPassword("");
      setAuthenticated(true);
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function openAttempts(jobId: string) {
    setSelectedJobId(jobId);
    try {
      setAttempts((await listAttempts(workspaceId, projectId, jobId)).items);
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function perform(action: "cancel" | "retry", jobId: string) {
    try {
      if (action === "cancel") await cancelJob(workspaceId, projectId, jobId);
      else await retryJob(workspaceId, projectId, jobId);
      await refreshJobs();
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  return (
    <main className="content" aria-labelledby="job-center-title">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h1 id="job-center-title">Job Center</h1>
            <p className="muted">Job 与 Attempt 的权威状态来自 Control Plane。</p>
          </div>
          <button type="button" onClick={onClose}>关闭</button>
        </div>
        {error ? <p role="alert">{error}</p> : null}
        {health ? <p><span>{health.profile}</span> · API <span>v{health.api_contract_version}</span> · {health.status}</p> : null}
        {!authenticated ? (
          <form onSubmit={submitLogin} aria-label="登录 Control Plane">
            <label>账号<input value={username} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
            <button type="submit">登录</button>
          </form>
        ) : (
          <>
            <div className="panel-header">
              <label>Workspace
                <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>
                  {workspaces.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}
                </select>
              </label>
              <label>Project
                <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                  {projects.map((item) => <option key={item.project_id} value={item.project_id}>{item.name}</option>)}
                </select>
              </label>
              <button type="button" onClick={() => void refreshJobs()}>刷新</button>
            </div>
            <table>
              <thead><tr><th>类型</th><th>状态</th><th>Attempt</th><th>错误</th><th>操作</th></tr></thead>
              <tbody>{jobs.map((job) => (
                <tr key={job.job_id}>
                  <td><button type="button" onClick={() => void openAttempts(job.job_id)}>{job.job_type}</button></td>
                  <td>{job.status}</td><td>{job.current_attempt_number}/{job.max_attempts}</td>
                  <td>{job.error_code ?? "-"}</td>
                  <td>
                    {!isTerminal(job.status) ? <button type="button" onClick={() => void perform("cancel", job.job_id)}>取消</button> : null}
                    {isTerminal(job.status) ? <button type="button" onClick={() => void perform("retry", job.job_id)}>重试</button> : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
            {selectedJobId ? (
              <section aria-label="Attempt 列表">
                <h2>Attempts</h2>
                <ul>{attempts.map((attempt) => (
                  <li key={attempt.attempt_id}>#{attempt.attempt_number} {attempt.status} {attempt.error_code ?? ""}</li>
                ))}</ul>
              </section>
            ) : null}
          </>
        )}
      </section>
    </main>
  );
}

function isTerminal(status: JobView["status"]): boolean {
  return ["completed", "partial", "failed", "cancelled", "dead"].includes(status);
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "platform_unavailable";
}
