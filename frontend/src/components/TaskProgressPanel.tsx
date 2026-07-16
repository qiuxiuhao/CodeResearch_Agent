import type { TaskProgress } from "../types/analysis";

export function TaskProgressPanel({ progress }: { progress: TaskProgress }) {
  const percent = Math.max(0, Math.min(100, progress.percent ?? 0));
  const steps = progress.steps ?? [];
  const completedNodes = progress.completed_nodes ?? 0;
  const totalNodes = progress.total_nodes ?? steps.length;
  const status = progress.status ?? "running";
  return (
    <div className={`analysis-progress ${status}`} aria-live="polite">
      <div className="progress-header">
        <div>
          <strong>{status === "completed" ? "分析完成" : status === "failed" ? "分析失败" : "分析中"}</strong>
          <span>{progress.current_label || "准备运行分析图"}</span>
        </div>
        <b>{percent}%</b>
      </div>
      <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="progress-meta">
        <span>节点 {completedNodes}/{totalNodes}</span>
        <span>{progress.task_id}</span>
      </div>
      {steps.length > 0 && (
        <div className="progress-steps" aria-label="LangGraph 节点进度">
          {steps.map((step) => (
            <span className={`progress-step ${step.status}`} key={step.id} title={step.label}>
              {step.label}
            </span>
          ))}
        </div>
      )}
      {progress.error && <p className="inline-error">{progress.error}</p>}
    </div>
  );
}
