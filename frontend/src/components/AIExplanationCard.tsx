import type { LLMExplanation, Mode } from "../types/analysis";

export function AIExplanationCard({ explanation, mode }: { explanation?: LLMExplanation; mode: Mode }) {
  if (!explanation) return null;
  const summary = explanation.summary || explanation.alignment_summary;
  const lists = [
    ["逻辑概览", explanation.logic_summary],
    ["阅读建议", explanation.reading_guide],
    ["关键关系", explanation.key_relationships],
    ["数据流", explanation.data_flow_explanation],
    ["模块说明", explanation.module_explanations],
    ["证据理解", explanation.evidence_interpretation]
  ] as const;
  const metadata = explanation.metadata;
  return (
    <section className="ai-card" aria-label="AI 增强解释">
      <h4 className="ai-card-title">AI 增强解释（基于静态分析事实）</h4>
      {summary && <p>{summary}</p>}
      {explanation.architecture_role && <p>架构位置：{explanation.architecture_role}</p>}
      {mode === "beginner" && explanation.teaching_explanation && <p>{explanation.teaching_explanation}</p>}
      {lists.map(([title, items]) => items && items.length > 0 ? (
        <section key={title}><h4>{title}</h4><ul>{items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul></section>
      ) : null)}
      {mode === "beginner" && explanation.learning_notes && explanation.learning_notes.length > 0 && (
        <section><h4>学习提示</h4><ul>{explanation.learning_notes.map((item, index) => <li key={index}>{item}</li>)}</ul></section>
      )}
      {explanation.uncertainties && explanation.uncertainties.length > 0 && <p className="muted">不确定项：{explanation.uncertainties.join("；")}</p>}
      {explanation.evidence_refs && explanation.evidence_refs.length > 0 && <p className="muted">证据：{explanation.evidence_refs.join(", ")}</p>}
      {metadata && <p className="muted">{metadata.provider}/{metadata.model}{metadata.cache_hit ? " · 缓存命中" : ""}{metadata.total_tokens != null ? ` · ${metadata.total_tokens} tokens` : ""}</p>}
    </section>
  );
}
