import type { LLMExplanations } from "../types/analysis";

export function AIStatusBanner({ llm }: { llm?: LLMExplanations }) {
  if (!llm || llm.analysis_mode === "rule" || llm.status === "disabled") {
    return <p className="ai-status muted">当前使用规则模式，未发送外部模型请求。</p>;
  }
  const budget = llm.budget ?? {};
  return (
    <div className={`ai-status ${llm.status ?? "skipped"}`}>
      <strong>AI 增强：{llm.status ?? "unknown"}</strong>
      <span>逻辑实体 {budget.selected_entities ?? 0}/{budget.max_total_entities ?? 0}</span>
      <span>Provider 请求 {budget.sent_provider_requests ?? 0}/{budget.max_provider_requests ?? 0}</span>
      <span>缓存命中 {budget.cache_hits ?? llm.usage?.cache_hits ?? 0}</span>
    </div>
  );
}
