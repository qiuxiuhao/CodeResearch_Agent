import { useMemo, useState } from "react";
import type { AnalysisResult, Mode } from "../types/analysis";
import { EmptyState } from "./EmptyState";
import { AIExplanationCard } from "./AIExplanationCard";
import { DetailViewSwitch } from "./DetailViewSwitch";

export function ModelAnalysisPanel({ result, mode }: { result: AnalysisResult; mode: Mode }) {
  const models = result.model_analysis?.model_analysis ?? [];
  const [selectedKey, setSelectedKey] = useState<string | null>(models[0] ? modelKey(models[0], 0) : null);
  const selected = useMemo(
    () => models.find((model, index) => modelKey(model, index) === selectedKey) ?? models[0],
    [models, selectedKey]
  );
  const explanation = result.llm_explanations?.model_explanations?.find(
    (item) => item.file_path === selected?.file_path && item.class_name === selected?.class_name
  );
  const selectedModelKey = selected ? modelKey(selected, models.indexOf(selected)) : null;
  if (models.length === 0) {
    return <EmptyState message="暂无模型网络结构分析。" />;
  }
  return (
    <section className="tab-content">
      <h2>模型网络结构分析</h2>
      <div className="split">
        <div className="list" aria-label="模型列表">
          {models.map((model, index) => (
            <button
              className={`list-button ${selectedModelKey === modelKey(model, index) ? "active" : ""}`}
              key={modelKey(model, index)}
              onClick={() => setSelectedKey(modelKey(model, index))}
              type="button"
            >
              <strong>{String(model.class_name ?? "Model")}</strong>
              <small>{String(model.file_path ?? "")}</small>
            </button>
          ))}
        </div>
        {selected && (
          <article className="item-card detail-card">
            <h3>{String(selected.class_name ?? "Model")}</h3>
            <DetailViewSwitch
              aiAvailable={Boolean(explanation)}
              ai={<AIExplanationCard mode={mode} explanation={explanation} />}
              basic={
                <>
                  <p>文件：{String(selected.file_path ?? "")}</p>
                  <p>主模型候选：{selected.is_main_model_candidate ? "是" : "否"}</p>
                  <p>输入：{asList(selected.model_inputs).join(", ") || "无"}</p>
                  <p>输出：{asList(selected.model_outputs).join(", ") || "无"}</p>
                  <h4>网络层</h4>
                  <ul>
                    {asRecords(selected.layers).map((layer, layerIndex) => (
                      <li key={`${layer.assigned_name}-${layerIndex}`}>
                        {String(layer.assigned_name ?? layer.name ?? "")}：{String(layer.layer_type ?? "")}（{String(layer.role ?? "unknown")}）
                      </li>
                    ))}
                  </ul>
                  <h4>Forward 主要流程</h4>
                  <ol>
                    {asRecords(selected.forward_steps).map((step, stepIndex) => (
                      <li key={`${step.order}-${stepIndex}`}>{String(step.explanation ?? step.expression ?? "")}</li>
                    ))}
                  </ol>
                </>
              }
            />
          </article>
        )}
      </div>
    </section>
  );
}

function modelKey(model: Record<string, unknown>, index: number): string {
  return `${String(model.file_path ?? "")}:${String(model.class_name ?? "Model")}:${index}`;
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}
