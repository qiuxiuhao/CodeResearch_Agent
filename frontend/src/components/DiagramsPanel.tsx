import { useMemo, useState } from "react";
import type { AnalysisResult, Diagram, TeachingDiagramItem } from "../types/analysis";
import { teachingDiagramAssetUrl } from "../api/client";
import { EmptyState } from "./EmptyState";
import { MermaidBlock } from "./MermaidBlock";

type TeachingView = "blueprint" | "ai";

export function DiagramsPanel({ result }: { result: AnalysisResult }) {
  const diagrams = result.diagrams?.diagrams ?? [];
  const teachingDiagrams = result.teaching_diagrams?.diagrams ?? [];
  if (diagrams.length === 0 && teachingDiagrams.length === 0) {
    return <EmptyState message="暂无图示分析。" />;
  }
  return (
    <section className="tab-content">
      {teachingDiagrams.length > 0 ? (
        <>
          <h2>教学图</h2>
          <p className="muted">AI 教学示意图可能做了视觉简化，请以规则分析和本地 Blueprint 为准。</p>
          <TeachingDiagramBrowser result={result} diagrams={teachingDiagrams} />
        </>
      ) : (
        <>
          <h2>图示分析</h2>
          <MermaidDiagramBrowser diagrams={diagrams} />
        </>
      )}
    </section>
  );
}

function MermaidDiagramBrowser({ diagrams }: { diagrams: Diagram[] }) {
  const [selectedKey, setSelectedKey] = useState<string | null>(diagrams[0] ? diagramKey(diagrams[0], 0) : null);
  const selected = useMemo(
    () => diagrams.find((diagram, index) => diagramKey(diagram, index) === selectedKey) ?? diagrams[0],
    [diagrams, selectedKey]
  );
  if (!selected) return <EmptyState message="暂无 Mermaid 图示。" />;
  return (
    <div className="split diagram-browser">
      <div className="list" aria-label="Mermaid 图列表">
        {diagrams.map((diagram, index) => {
          const id = diagramKey(diagram, index);
          return (
            <button
              className={`list-button ${selected === diagram ? "active" : ""}`}
              key={id}
              onClick={() => setSelectedKey(id)}
              type="button"
            >
              <strong>{diagram.title || id}</strong>
              <small>{diagram.diagram_type || id}</small>
            </button>
          );
        })}
      </div>
      <article className="item-card detail-card">
        <h3>{selected.title || selected.id}</h3>
        <p>{selected.description}</p>
        <MermaidBlock code={selected.mermaid || ""} />
        {(selected.warnings ?? []).map((warning) => (
          <p className="muted" key={warning}>注意：{warning}</p>
        ))}
      </article>
    </div>
  );
}

function diagramKey(diagram: Diagram, index: number): string {
  return diagram.id ?? `${diagram.title ?? "diagram"}-${index}`;
}

function TeachingDiagramBrowser({ result, diagrams }: { result: AnalysisResult; diagrams: TeachingDiagramItem[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(diagrams[0]?.diagram_id ?? null);
  const selected = useMemo(
    () => diagrams.find((diagram) => diagram.diagram_id === selectedId) ?? diagrams[0],
    [diagrams, selectedId]
  );
  if (!selected) return <EmptyState message="暂无教学图。" />;
  return (
    <div className="split diagram-browser">
      <div className="list" aria-label="教学图列表">
        {diagrams.map((diagram) => (
          <button
            className={`list-button ${selected.diagram_id === diagram.diagram_id ? "active" : ""}`}
            key={diagram.diagram_id}
            onClick={() => setSelectedId(diagram.diagram_id)}
            type="button"
          >
            <strong>{diagram.title || diagram.diagram_id}</strong>
            <small>{diagram.source_entity?.file_path || diagram.source_entity?.qualified_name || diagram.diagram_id}</small>
          </button>
        ))}
      </div>
      <TeachingDiagramCard key={selected.diagram_id} result={result} diagram={selected} />
    </div>
  );
}

function TeachingDiagramCard({ result, diagram }: { result: AnalysisResult; diagram: TeachingDiagramItem }) {
  const hasAi = Boolean(diagram.final_asset);
  const [view, setView] = useState<TeachingView>(hasAi && diagram.display_variant === "ai" ? "ai" : "blueprint");
  const preferSvgBlueprint = (diagram.warnings ?? []).includes("teaching_diagram_font_unavailable");
  return (
    <article className="item-card detail-card">
      <h3>{diagram.title || diagram.diagram_id}</h3>
      <div className="button-row">
        <button className={view === "blueprint" ? "primary-button" : "secondary-button"} type="button" onClick={() => setView("blueprint")}>
          Blueprint
        </button>
        <button className={view === "ai" ? "primary-button" : "secondary-button"} disabled={!hasAi} type="button" onClick={() => setView("ai")}>
          AI 教学图
        </button>
      </div>
      {view === "blueprint" && (diagram.blueprint_png || diagram.blueprint_svg) && (
        <img
          className="figure-preview"
          src={teachingDiagramAssetUrl(result.task_id, diagram.diagram_id, preferSvgBlueprint && diagram.blueprint_svg ? "blueprint.svg" : "blueprint.png")}
          alt={`${diagram.title} Blueprint`}
        />
      )}
      {view === "blueprint" && !diagram.blueprint_png && !diagram.blueprint_svg && <p className="muted">暂无 Blueprint 图。</p>}
      {view === "ai" && hasAi && (
        <>
          <img className="figure-preview" src={teachingDiagramAssetUrl(result.task_id, diagram.diagram_id, "final.png")} alt={`${diagram.title} AI 教学图`} />
          <p className="muted">AI 教学示意图可能存在简化，已由本地程序覆盖模块文字、Shape、公式、箭头和图例。</p>
        </>
      )}
      {!hasAi && view === "blueprint" && (
        <p className="muted">AI 图未通过审查或未启用，当前回退到本地准确 Blueprint。{diagram.fallback_reason ? `原因：${diagram.fallback_reason}` : ""}</p>
      )}
      {(diagram.warnings ?? []).map((warning) => (
        <p className="muted" key={warning}>注意：{warning}</p>
      ))}
    </article>
  );
}
