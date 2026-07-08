import type { AnalysisResult } from "../types/analysis";

export function SummaryCards({ result }: { result: AnalysisResult }) {
  const summary = result.summary ?? {};
  const metrics = [
    ["Python 文件", summary.python_file_count],
    ["类", summary.class_count],
    ["函数", summary.function_count],
    ["库函数调用", summary.library_call_count],
    ["模型", summary.model_count],
    ["论文贡献", summary.paper_contribution_count],
    ["图示", summary.diagram_count]
  ];
  return (
    <section className="tab-content">
      <h2>项目总览</h2>
      <div className="summary-grid">
        {metrics.map(([label, value]) => (
          <div className="metric" key={label}>
            <span>{label}</span>
            <strong>{value ?? 0}</strong>
          </div>
        ))}
      </div>
      <p className="muted">任务：{result.task_id}</p>
    </section>
  );
}
