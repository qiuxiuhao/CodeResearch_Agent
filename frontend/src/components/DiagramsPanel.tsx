import type { AnalysisResult } from "../types/analysis";
import { EmptyState } from "./EmptyState";
import { MermaidBlock } from "./MermaidBlock";

export function DiagramsPanel({ result }: { result: AnalysisResult }) {
  const diagrams = result.diagrams?.diagrams ?? [];
  if (diagrams.length === 0) {
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
    </section>
  );
}
