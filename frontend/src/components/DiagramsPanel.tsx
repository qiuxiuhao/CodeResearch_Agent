import { useState } from "react";
import type { AnalysisResult, TeachingDiagramItem } from "../types/analysis";
import { teachingDiagramAssetUrl } from "../api/client";
import { EmptyState } from "./EmptyState";
import { MermaidBlock } from "./MermaidBlock";

type TeachingView = "mermaid" | "blueprint" | "ai";

export function DiagramsPanel({ result }: { result: AnalysisResult }) {
  const diagrams = result.diagrams?.diagrams ?? [];
  const teachingDiagrams = result.teaching_diagrams?.diagrams ?? [];
  if (diagrams.length === 0 && teachingDiagrams.length === 0) {
    return <EmptyState message="暂无图示分析。" />;
  }
  return (
    <section className="tab-content">
      <h2>图示分析</h2>
      {diagrams.map((diagram) => (
        <article className="item-card" key={diagram.id}>
          <h3>{diagram.title || diagram.id}</h3>
          <p>{diagram.description}</p>
          <MermaidBlock code={diagram.mermaid || ""} />
          {(diagram.warnings ?? []).map((warning) => (
            <p className="muted" key={warning}>注意：{warning}</p>
          ))}
        </article>
      ))}
      {teachingDiagrams.length > 0 && (
        <>
          <h2>教学图</h2>
          <p className="muted">AI 教学示意图可能做了视觉简化，请以规则分析和本地 Blueprint 为准。</p>
          {teachingDiagrams.map((diagram) => (
            <TeachingDiagramCard key={diagram.diagram_id} result={result} diagram={diagram} />
          ))}
        </>
      )}
    </section>
  );
}

function TeachingDiagramCard({ result, diagram }: { result: AnalysisResult; diagram: TeachingDiagramItem }) {
  const [view, setView] = useState<TeachingView>(diagram.display_variant === "ai" ? "ai" : "blueprint");
  const relatedMermaid = (result.diagrams?.diagrams ?? []).filter((item) => diagram.related_mermaid_diagram_ids?.includes(item.id || ""));
  const hasAi = Boolean(diagram.final_asset && diagram.display_variant === "ai");
  const preferSvgBlueprint = (diagram.warnings ?? []).includes("teaching_diagram_font_unavailable");
  return (
    <article className="item-card">
      <h3>{diagram.title || diagram.diagram_id}</h3>
      <div className="button-row">
        <button className={view === "mermaid" ? "primary-button" : "secondary-button"} type="button" onClick={() => setView("mermaid")}>
          Mermaid
        </button>
        <button className={view === "blueprint" ? "primary-button" : "secondary-button"} type="button" onClick={() => setView("blueprint")}>
          Blueprint
        </button>
        <button className={view === "ai" ? "primary-button" : "secondary-button"} disabled={!hasAi} type="button" onClick={() => setView("ai")}>
          AI 教学图
        </button>
      </div>
      {view === "mermaid" && (
        relatedMermaid.length > 0 ? relatedMermaid.map((item) => <MermaidBlock key={item.id} code={item.mermaid || ""} />) : <p className="muted">未找到直接映射的 Mermaid 图。</p>
      )}
      {view === "blueprint" && (diagram.blueprint_png || diagram.blueprint_svg) && (
        <img
          className="figure-preview"
          src={teachingDiagramAssetUrl(result.task_id, diagram.diagram_id, preferSvgBlueprint && diagram.blueprint_svg ? "blueprint.svg" : "blueprint.png")}
          alt={`${diagram.title} Blueprint`}
        />
      )}
      {view === "ai" && hasAi && (
        <>
          <img className="figure-preview" src={teachingDiagramAssetUrl(result.task_id, diagram.diagram_id, "final.png")} alt={`${diagram.title} AI 教学图`} />
          <p className="muted">AI 教学示意图可能存在简化，已由本地程序覆盖模块文字、Shape、公式、箭头和图例。</p>
        </>
      )}
      {!hasAi && (
        <p className="muted">AI 图未通过审查或未启用，当前回退到本地准确 Blueprint。{diagram.fallback_reason ? `原因：${diagram.fallback_reason}` : ""}</p>
      )}
      {(diagram.warnings ?? []).map((warning) => (
        <p className="muted" key={warning}>注意：{warning}</p>
      ))}
    </article>
  );
}
