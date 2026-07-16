import { useMemo, useState } from "react";
import type { AnalysisResult, Mode } from "../types/analysis";
import { EmptyState } from "./EmptyState";
import { AIExplanationCard } from "./AIExplanationCard";
import { DetailViewSwitch } from "./DetailViewSwitch";

export function FileAnalysisPanel({ result, mode }: { result: AnalysisResult; mode: Mode }) {
  const files = result.file_analysis?.file_analysis ?? [];
  const [selectedPath, setSelectedPath] = useState<string | null>(files[0] ? String(files[0].file_path ?? "") : null);
  const selected = useMemo(
    () => files.find((file) => String(file.file_path ?? "") === selectedPath) ?? files[0],
    [files, selectedPath]
  );
  const explanation = result.llm_explanations?.file_explanations?.find((item) => item.file_path === selected?.file_path);
  if (files.length === 0) {
    return <EmptyState message="暂无文件级分析。" />;
  }
  return (
    <section className="tab-content">
      <h2>文件级分析</h2>
      <div className="split">
        <div className="list" aria-label="文件列表">
          {files.map((file, index) => {
            const filePath = String(file.file_path ?? `file-${index}`);
            return (
              <button
                className={`list-button ${selected && String(selected.file_path ?? "") === filePath ? "active" : ""}`}
                key={`${filePath}-${index}`}
                onClick={() => setSelectedPath(filePath)}
                type="button"
              >
                <strong>{filePath}</strong>
                <small>{String(file.file_type ?? "unknown")}</small>
              </button>
            );
          })}
        </div>
        {selected && (
          <article className="item-card detail-card">
            <h3>{String(selected.file_path ?? "unknown")}</h3>
            <DetailViewSwitch
              aiAvailable={Boolean(explanation)}
              ai={<AIExplanationCard mode={mode} explanation={explanation} />}
              basic={
                <>
                  <p>类型：{String(selected.file_type ?? "unknown")}</p>
                  <p>{String(selected.purpose ?? "")}</p>
                  <p className="muted">{String(selected.project_position ?? "")}</p>
                  <p>主要类：{asList(selected.main_classes).join(", ") || "无"}</p>
                  <p>主要函数：{asList(selected.main_functions).join(", ") || "无"}</p>
                </>
              }
            />
          </article>
        )}
      </div>
    </section>
  );
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}
