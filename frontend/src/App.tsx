import { useEffect, useMemo, useState } from "react";
import { AppShell } from "./components/AppShell";
import { ErrorBanner } from "./components/ErrorBanner";
import { LibraryFunctionModal } from "./components/LibraryFunctionModal";
import { LoadingState } from "./components/LoadingState";
import { ResultTabs } from "./components/ResultTabs";
import { TaskForm } from "./components/TaskForm";
import { ProviderSettingsDrawer } from "./components/ProviderSettingsDrawer";
import { getTaskResult, listTasks } from "./api/client";
import type { AnalysisResult, LibraryCall, Mode, ResultTab, TaskSummary } from "./types/analysis";
import { TraceExplorer } from "./features/observability/TraceExplorer";

export default function App() {
  const [mode, setMode] = useState<Mode>("normal");
  const [activeTab, setActiveTab] = useState<ResultTab>("overview");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLibraryCall, setSelectedLibraryCall] = useState<LibraryCall | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [observabilityOpen, setObservabilityOpen] = useState(false);

  useEffect(() => {
    void refreshTasks();
  }, []);

  const docsByName = useMemo(() => {
    const docs = result?.library_function_docs?.library_function_docs ?? [];
    return new Map(docs.map((doc) => [doc.canonical_name, doc]));
  }, [result]);

  async function refreshTasks() {
    try {
      const response = await listTasks();
      setTasks(response.tasks);
    } catch {
      // Recent tasks are optional for the MVP.
    }
  }

  async function loadResult(taskId: string) {
    setIsLoading(true);
    setError(null);
    try {
      const nextResult = await getTaskResult(taskId);
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

  return (
    <AppShell
      mode={mode}
      onModeChange={setMode}
      onOpenSettings={() => setSettingsOpen(true)}
      onOpenObservability={() => setObservabilityOpen(true)}
    >
      {observabilityOpen ? (
        <TraceExplorer onClose={() => setObservabilityOpen(false)} />
      ) : (
        <>
      <aside className="sidebar">
        <TaskForm onTaskCreated={handleTaskCreated} onError={setError} onOpenSettings={() => setSettingsOpen(true)} />
        <section className="panel">
          <h2>最近任务</h2>
          {tasks.length === 0 ? (
            <p className="muted">暂无历史任务</p>
          ) : (
            <div className="task-list">
              {tasks.map((task) => (
                <button key={task.task_id} className="task-button" onClick={() => task.task_id && loadResult(task.task_id)}>
                  <span>{task.task_id}</span>
                  <small>{task.has_diagrams ? "含图示" : "无图示"}</small>
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
