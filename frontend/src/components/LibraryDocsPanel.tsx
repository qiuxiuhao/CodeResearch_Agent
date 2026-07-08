import type { AnalysisResult } from "../types/analysis";
import { EmptyState } from "./EmptyState";

export function LibraryDocsPanel({ result }: { result: AnalysisResult }) {
  const docs = result.library_function_docs?.library_function_docs ?? [];
  if (docs.length === 0) {
    return <EmptyState message="暂无 Python 库函数说明。" />;
  }
  return (
    <section className="tab-content">
      <h2>Python 库函数说明</h2>
      <div className="card-grid">
        {docs.map((doc) => (
          <article className="item-card" key={doc.canonical_name}>
            <h3>{doc.canonical_name}</h3>
            <p>{doc.summary}</p>
            <p className="muted">{doc.beginner_explanation}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
