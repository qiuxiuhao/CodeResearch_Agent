import type { AnalysisResult } from "../types/analysis";
import { EmptyState } from "./EmptyState";

export function FileAnalysisPanel({ result }: { result: AnalysisResult }) {
  const files = result.file_analysis?.file_analysis ?? [];
  if (files.length === 0) {
    return <EmptyState message="暂无文件级分析。" />;
  }
  return (
    <section className="tab-content">
      <h2>文件级分析</h2>
      <div className="card-grid">
        {files.map((file, index) => (
          <article className="item-card" key={`${file.file_path}-${index}`}>
            <h3>{String(file.file_path ?? "unknown")}</h3>
            <p>类型：{String(file.file_type ?? "unknown")}</p>
            <p>{String(file.purpose ?? "")}</p>
            <p className="muted">{String(file.project_position ?? "")}</p>
            <p>主要类：{asList(file.main_classes).join(", ") || "无"}</p>
            <p>主要函数：{asList(file.main_functions).join(", ") || "无"}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}
