import type { AnalysisResult } from "../types/analysis";
import { EmptyState } from "./EmptyState";

export function ModelAnalysisPanel({ result }: { result: AnalysisResult }) {
  const models = result.model_analysis?.model_analysis ?? [];
  if (models.length === 0) {
    return <EmptyState message="暂无模型网络结构分析。" />;
  }
  return (
    <section className="tab-content">
      <h2>模型网络结构分析</h2>
      <div className="card-grid">
        {models.map((model, index) => (
          <article className="item-card" key={`${model.class_name}-${index}`}>
            <h3>{String(model.class_name ?? "Model")}</h3>
            <p>文件：{String(model.file_path ?? "")}</p>
            <p>主模型候选：{model.is_main_model_candidate ? "是" : "否"}</p>
            <p>输入：{asList(model.model_inputs).join(", ") || "无"}</p>
            <p>输出：{asList(model.model_outputs).join(", ") || "无"}</p>
            <h4>网络层</h4>
            <ul>
              {asRecords(model.layers).map((layer, layerIndex) => (
                <li key={`${layer.assigned_name}-${layerIndex}`}>
                  {String(layer.assigned_name ?? layer.name ?? "")}：{String(layer.layer_type ?? "")}（{String(layer.role ?? "unknown")}）
                </li>
              ))}
            </ul>
            <h4>Forward 主要流程</h4>
            <ol>
              {asRecords(model.forward_steps).map((step, stepIndex) => (
                <li key={`${step.order}-${stepIndex}`}>{String(step.explanation ?? step.expression ?? "")}</li>
              ))}
            </ol>
          </article>
        ))}
      </div>
    </section>
  );
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}
