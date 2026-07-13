import type { AnalysisResult, Mode } from "../types/analysis";
import { EmptyState } from "./EmptyState";
import { AIExplanationCard } from "./AIExplanationCard";

export function PaperAnalysisPanel({ result, mode }: { result: AnalysisResult; mode: Mode }) {
  const paper = result.paper_analysis?.paper_analysis;
  const alignment = result.paper_code_alignment?.paper_code_alignment;
  if (!paper?.paper_provided) {
    return <EmptyState message="未提供论文 PDF，跳过论文解析与论文代码对齐。" />;
  }
  const contributions = asRecords(paper.contributions);
  const alignmentItems = asRecords(alignment?.alignment_items);
  return (
    <section className="tab-content">
      <h2>论文解析与论文代码对齐</h2>
      <p>标题：{String(paper.title ?? "未识别")}</p>
      <p>{String(paper.abstract ?? "暂无摘要").slice(0, 360)}</p>
      <h3>核心创新点</h3>
      <div className="card-grid">
        {contributions.map((item) => (
          <article className="item-card" key={String(item.id)}>
            <h4>{String(item.id)} {String(item.title ?? "")}</h4>
            <p>{String(item.description ?? "")}</p>
            <p className="muted">置信度：{String(item.confidence ?? "low")}</p>
          </article>
        ))}
      </div>
      <h3>代码对齐</h3>
      <div className="card-grid">
        {alignmentItems.map((item, index) => (
          <article className="item-card" key={`${item.contribution_id}-${index}`}>
            <h4>{String(item.contribution_id)} {String(item.status)}</h4>
            <p>{String(item.reason ?? "")}</p>
            <p className="muted">置信度：{String(item.confidence ?? "low")}</p>
            <AIExplanationCard
              mode={mode}
              explanation={result.llm_explanations?.paper_code_alignment_explanations?.find(
                (explanation) => explanation.contribution_id === item.contribution_id
              )}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}
