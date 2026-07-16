import { CheckCircle2, CircleSlash, Image, MessageSquareText, RefreshCcw, ScanEye, Sparkles, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { AIUsage, AIUsageGroup } from "../types/analysis";

const GROUPS: Array<[keyof AIUsage, string, LucideIcon]> = [
  ["text_analysis", "普通文本 LLM", MessageSquareText],
  ["teaching_narrative", "教学文案 LLM", Sparkles],
  ["paper_vision", "论文 Figure VLM", ScanEye],
  ["image_generation", "图片生成", Image],
  ["teaching_review", "教学图 VLM Review", RefreshCcw]
];

export function AIBudgetPanel({ usage }: { usage?: AIUsage }) {
  return (
    <section className="ai-budget-panel" aria-label="AI 能力预算状态">
      <div className="section-heading">
        <h2>AI 能力状态</h2>
        <span>请求数 / 预算 / 缓存 / 告警</span>
      </div>
      <div className="ai-budget-grid">
        {GROUPS.map(([key, label, Icon]) => (
          <BudgetRow key={key} label={label} usage={usage?.[key]} icon={Icon} />
        ))}
      </div>
    </section>
  );
}

function BudgetRow({ label, usage, icon: Icon }: { label: string; usage?: AIUsageGroup; icon: LucideIcon }) {
  const enabled = Boolean(usage?.enabled);
  const consent = Boolean(usage?.consent);
  const configured = usage?.configured;
  const configuredKnown = typeof configured === "boolean";
  const warningCodes = usage?.warnings?.filter(Boolean) ?? [];
  const warningTitle = warningCodes.length ? `相关告警：${warningCodes.join("，")}` : undefined;
  const ready = enabled && consent && configured !== false;
  const stateLabel = !enabled ? "关闭" : !consent ? "缺少授权" : configured === false ? "缺少配置" : "可用";
  const StatusIcon = !enabled ? CircleSlash : ready ? CheckCircle2 : TriangleAlert;
  return (
    <article className={`ai-budget-row ${ready ? "ready" : enabled ? "warning" : "off"}`}>
      <div className="ai-budget-title">
        <Icon aria-hidden="true" size={18} />
        <strong>{label}</strong>
      </div>
      <div className="ai-budget-state">
        <StatusIcon aria-hidden="true" size={16} />
        <span>{stateLabel}</span>
        {configuredKnown && <small>{configured ? "Provider 已配置" : "Provider 未配置"}</small>}
      </div>
      <div className="ai-budget-metrics">
        <span>请求 {usage?.request_count ?? 0}/{usage?.budget_limit ?? 0}</span>
        <span>实体 {usage?.selected_entities ?? 0}</span>
        <span>缓存 {usage?.cache_hits ?? 0}</span>
        <span>fallback {usage?.fallbacks ?? 0}</span>
        <span title={warningTitle}>告警 {usage?.failures ?? 0}</span>
      </div>
      {(usage?.provider || usage?.model) && (
        <p className="provider-line">{usage.provider ?? "provider"} / {usage.model ?? "model"}</p>
      )}
    </article>
  );
}
