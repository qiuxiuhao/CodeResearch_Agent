import { BookOpenText, Boxes, FileCode2, GitBranch, Layers3, Sigma } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getProviderSettings } from "../api/client";
import { PROVIDER_SETTINGS_UPDATED } from "../providerSettingsEvents";
import type { AIUsage, AnalysisResult, ProviderPublicSettings } from "../types/analysis";
import { AIBudgetPanel } from "./AIBudgetPanel";

type UsageKey = keyof AIUsage;

const PROVIDER_GROUP_BY_USAGE: Record<UsageKey, ProviderPublicSettings["group"]> = {
  text_analysis: "text_llm",
  teaching_narrative: "text_llm",
  paper_vision: "vision_vlm",
  image_generation: "image_generation",
  teaching_review: "vision_vlm"
};

export function DashboardOverview({ result }: { result: AnalysisResult }) {
  const summary = result.summary ?? {};
  const [providers, setProviders] = useState<ProviderPublicSettings[]>([]);
  const usage = useMemo(
    () => mergeCurrentProviderStatus(result.ai_usage ?? summary.ai_usage, providers),
    [summary.ai_usage, result.ai_usage, providers]
  );

  useEffect(() => {
    let active = true;
    async function refreshProviders() {
      try {
        const response = await getProviderSettings();
        if (active) setProviders(response.providers);
      } catch {
        if (active) setProviders([]);
      }
    }
    void refreshProviders();
    const handleProviderUpdate = () => {
      void refreshProviders();
    };
    window.addEventListener(PROVIDER_SETTINGS_UPDATED, handleProviderUpdate);
    return () => {
      active = false;
      window.removeEventListener(PROVIDER_SETTINGS_UPDATED, handleProviderUpdate);
    };
  }, []);

  const metrics: Array<[string, number | undefined, LucideIcon]> = [
    ["Python 文件", summary.python_file_count, FileCode2],
    ["类", summary.class_count, Boxes],
    ["函数", summary.function_count, Sigma],
    ["库函数调用", summary.library_call_count, GitBranch],
    ["模型", summary.model_count, Layers3],
    ["论文贡献", summary.paper_contribution_count, BookOpenText]
  ];
  const recentOutputs: Array<[string, boolean]> = [
    ["报告", Boolean(result.report_md)],
    ["Mermaid 图示", Boolean(result.diagrams?.diagrams?.length)],
    ["教学图", Boolean(result.teaching_diagrams?.diagrams?.length)],
    ["论文 Figure", Boolean(result.paper_figure_analysis?.figures?.length)]
  ];
  return (
    <section className="dashboard-overview">
      <div className="overview-hero">
        <div>
          <p className="eyebrow">Task {result.task_id}</p>
          <h1>分析总览</h1>
        </div>
        <div className="overview-status-strip" aria-label="核心状态">
          <span>{summary.llm_status ?? "llm-disabled"}</span>
          <span>{summary.vision_status ?? "vision-disabled"}</span>
          <span>{summary.teaching_diagram_status ?? "diagram-disabled"}</span>
        </div>
      </div>
      <div className="summary-grid">
        {metrics.map(([label, value, Icon]) => (
          <article className="metric" key={String(label)}>
            <Icon aria-hidden="true" size={20} />
            <span>{label}</span>
            <strong>{value ?? 0}</strong>
          </article>
        ))}
      </div>
      <AIBudgetPanel usage={usage} />
      <section className="recent-output-panel">
        <div className="section-heading">
          <h2>最近输出</h2>
          <span>结构化产物与可视化结果</span>
        </div>
        <div className="recent-output-list">
          {recentOutputs.map(([label, ready]) => (
            <span className={ready ? "output-ready" : "output-muted"} key={String(label)}>
              {label}：{ready ? "已生成" : "暂无"}
            </span>
          ))}
        </div>
      </section>
    </section>
  );
}

function mergeCurrentProviderStatus(usage: AIUsage | undefined, providers: ProviderPublicSettings[]): AIUsage | undefined {
  if (!usage || providers.length === 0) return usage;
  const next: AIUsage = { ...usage };
  (Object.entries(PROVIDER_GROUP_BY_USAGE) as Array<[UsageKey, ProviderPublicSettings["group"]]>).forEach(([key, group]) => {
    const current = usage[key] ?? {};
    const groupProviders = providers.filter((provider) => provider.group === group);
    const enabledProviders = groupProviders.filter((provider) => provider.enabled);
    const configuredProvider = enabledProviders.find((provider) => provider.configured);
    const displayProvider = configuredProvider ?? enabledProviders[0] ?? groupProviders[0];
    const displayModel = typeof displayProvider?.fields.model === "string" ? displayProvider.fields.model : undefined;
    next[key] = {
      ...current,
      configured: Boolean(configuredProvider),
      provider: current.provider ?? displayProvider?.id ?? null,
      model: current.model ?? displayModel ?? null
    };
  });
  return next;
}
