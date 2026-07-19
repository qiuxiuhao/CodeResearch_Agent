import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AppShell } from "./components/AppShell";
import { ErrorBanner } from "./components/ErrorBanner";
import { LibraryFunctionModal } from "./components/LibraryFunctionModal";
import { LoadingState } from "./components/LoadingState";
import { ResultTabs } from "./components/ResultTabs";
import { TaskForm } from "./components/TaskForm";
import { ProviderSettingsDrawer } from "./components/ProviderSettingsDrawer";
import type { AnalysisResult, LibraryCall, Mode, ResultTab, TaskSummary } from "./types/analysis";
import {
  getAnalysisJobResult,
  listJobs,
  listProjects,
  listWorkspaces,
  login,
  restoreSession,
  setActiveScope,
  type ProjectView,
  type WorkspaceView
} from "./api/v2Client";
import { TraceExplorer } from "./features/observability/TraceExplorer";
import { EvaluationDashboard } from "./features/evaluation/EvaluationDashboard";
import { JobCenter } from "./features/platform/JobCenter";

export default function App() {
  const [session, setSession] = useState<"restoring" | "authenticated" | "anonymous">("restoring");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [workspaces, setWorkspaces] = useState<WorkspaceView[]>([]);
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [mode, setMode] = useState<Mode>("normal");
  const [activeTab, setActiveTab] = useState<ResultTab>("overview");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLibraryCall, setSelectedLibraryCall] = useState<LibraryCall | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [observabilityOpen, setObservabilityOpen] = useState(false);
  const [evaluationOpen, setEvaluationOpen] = useState(false);
  const [jobsOpen, setJobsOpen] = useState(false);

  useEffect(() => {
    void restoreSession().then(async (restored) => {
      setSession(restored ? "authenticated" : "anonymous");
      if (restored) await refreshWorkspaces();
    });
  }, []);

  useEffect(() => {
    if (!workspaceId) {
      setProjects([]);
      setProjectId("");
      return;
    }
    void listProjects(workspaceId).then(({items}) => {
      setProjects(items);
      setProjectId((current) => items.some((item) => item.project_id === current) ? current : items[0]?.project_id ?? "");
    }).catch((exc) => setError(exc instanceof Error ? exc.message : "加载 Project 失败"));
  }, [workspaceId]);

  useEffect(() => {
    setActiveScope(workspaceId, projectId);
    if (workspaceId && projectId) void refreshTasks(workspaceId, projectId);
    else setTasks([]);
  }, [workspaceId, projectId]);

  const docsByName = useMemo(() => {
    const docs = result?.library_function_docs?.library_function_docs ?? [];
    return new Map(docs.map((doc) => [doc.canonical_name, doc]));
  }, [result]);

  async function refreshWorkspaces() {
    const response = await listWorkspaces();
    setWorkspaces(response.items);
    setWorkspaceId((current) => response.items.some((item) => item.workspace_id === current) ? current : response.items[0]?.workspace_id ?? "");
  }

  async function refreshTasks(targetWorkspaceId = workspaceId, targetProjectId = projectId) {
    if (!targetWorkspaceId || !targetProjectId) return;
    try {
      const response = await listJobs(targetWorkspaceId, targetProjectId);
      setTasks(response.items.filter((job) => job.job_type === "analysis").map((job) => ({
        task_id: job.job_id,
        has_report: job.status === "completed" || job.status === "partial",
        has_diagrams: false
      })));
    } catch {
      // Recent tasks are optional for the MVP.
    }
  }

  async function loadResult(taskId: string) {
    if (!workspaceId || !projectId) return;
    setIsLoading(true);
    setError(null);
    try {
      const nextResult = await getAnalysisJobResult<AnalysisResult>(workspaceId, projectId, taskId);
      setResult(nextResult);
      setActiveTab("overview");
      await refreshTasks();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载任务结果失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleTaskCreated(summary: TaskSummary) {
    if (summary.task_id) {
      await loadResult(summary.task_id);
    }
  }

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await login(username, password);
      setSession("authenticated");
      await refreshWorkspaces();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "登录失败");
    }
  }

  return (
    <AppShell
      mode={mode}
      onModeChange={setMode}
      onOpenSettings={() => setSettingsOpen(true)}
      onOpenObservability={() => { setJobsOpen(false); setEvaluationOpen(false); setObservabilityOpen(true); }}
      onOpenEvaluation={() => { setJobsOpen(false); setObservabilityOpen(false); setEvaluationOpen(true); }}
      onOpenJobs={() => { setObservabilityOpen(false); setEvaluationOpen(false); setJobsOpen(true); }}
    >
      {session === "restoring" ? (
        <main className="content"><LoadingState message="正在恢复登录会话..." /></main>
      ) : session === "anonymous" ? (
        <main className="content">
          {error && <ErrorBanner message={error} />}
          <section className="panel">
            <h2>登录 Local Workspace</h2>
            <form className="task-form" onSubmit={handleLogin}>
              <label>账号<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
              <label>密码<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
              <button className="primary-button" type="submit">登录</button>
            </form>
          </section>
        </main>
      ) : jobsOpen ? (
        <JobCenter onClose={() => setJobsOpen(false)} />
      ) : evaluationOpen ? (
        <EvaluationDashboard onClose={() => setEvaluationOpen(false)} />
      ) : observabilityOpen ? (
        <TraceExplorer onClose={() => setObservabilityOpen(false)} />
      ) : (
        <>
      <aside className="sidebar">
        <section className="panel">
          <h2>当前范围</h2>
          <label>Workspace<select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>{workspaces.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}</select></label>
          <label>Project<select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((item) => <option key={item.project_id} value={item.project_id}>{item.name}</option>)}</select></label>
          {!workspaceId || !projectId ? <p className="muted">请先创建并选择 Workspace 与 Project。</p> : null}
        </section>
        <TaskForm workspaceId={workspaceId} projectId={projectId} onTaskCreated={handleTaskCreated} onError={setError} onOpenSettings={() => setSettingsOpen(true)} />
        <section className="panel">
          <h2>最近任务</h2>
          {tasks.length === 0 ? (
            <p className="muted">暂无历史任务</p>
          ) : (
            <div className="task-list">
              {tasks.map((task) => (
                <button key={task.task_id} className="task-button" disabled={!task.has_report} onClick={() => task.task_id && loadResult(task.task_id)}>
                  <span>{task.task_id}</span>
                  <small>{task.has_report ? (task.has_diagrams ? "含图示" : "可查看结果") : "运行中或未完成"}</small>
                </button>
              ))}
            </div>
          )}
        </section>
      </aside>
      <main className="content">
        {error && <ErrorBanner message={error} />}
        {isLoading && <LoadingState message="正在分析或加载任务结果..." />}
        {!isLoading ? (
          <ResultTabs
            activeTab={activeTab}
            mode={mode}
            result={result}
            onTabChange={setActiveTab}
            onLibraryCallClick={setSelectedLibraryCall}
          />
        ) : null}
      </main>
      {selectedLibraryCall && (
        <LibraryFunctionModal
          call={selectedLibraryCall}
          doc={docsByName.get(selectedLibraryCall.canonical_name ?? "")}
          onClose={() => setSelectedLibraryCall(null)}
        />
      )}
      <ProviderSettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </>
      )}
    </AppShell>
  );
}
