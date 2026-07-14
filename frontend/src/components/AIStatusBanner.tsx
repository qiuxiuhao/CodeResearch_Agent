import type { LLMExplanations } from "../types/analysis";

export function AIStatusBanner({ llm }: { llm?: LLMExplanations }) {
  if (!llm || llm.text_llm_enabled === false || llm.analysis_mode === "rule" || llm.status === "disabled") {
    return <p className="ai-status muted">文本 LLM：未启用。</p>;
  }
  const budget = llm.budget ?? {};
  return (
    <div className={`ai-status ${llm.status ?? "skipped"}`}>
      <strong>文本 LLM：{llm.status ?? "unknown"}</strong>
      <span>逻辑实体 {budget.selected_entities ?? 0}/{budget.max_total_entities ?? 0}</span>
      <span>Provider 请求 {budget.sent_provider_requests ?? 0}/{budget.max_provider_requests ?? 0}</span>
      <span>缓存命中 {budget.cache_hits ?? llm.usage?.cache_hits ?? 0}</span>
    </div>
  );
}
