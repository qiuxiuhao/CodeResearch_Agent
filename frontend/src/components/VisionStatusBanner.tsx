import type { PaperFigureAnalysis } from "../types/analysis";

export function VisionStatusBanner({ vision }: { vision?: PaperFigureAnalysis }) {
  if (!vision || !vision.vision_vlm_enabled || vision.vision_status === "disabled") {
    return <p className="ai-status muted">论文 VLM：未启用。Figure 仍可在本地确定性提取。</p>;
  }
  const budget = vision.budget ?? {};
  return (
    <div className={`ai-status ${vision.vision_status ?? "skipped"}`}>
      <strong>论文 VLM：{vision.vision_status ?? "unknown"}</strong>
      <span>Figure 实体 {budget.selected_entities ?? 0}/{budget.max_total_entities ?? 0}</span>
      <span>Provider 请求 {budget.sent_provider_requests ?? 0}/{budget.max_provider_requests ?? 0}</span>
      <span>缓存命中 {budget.cache_hits ?? 0}</span>
    </div>
  );
}
