import type { GlobalLibraryFunction } from "../types/analysis";
import { EmptyState } from "./EmptyState";

export function LowConfidenceFunctions({ items, onSelect }: { items: GlobalLibraryFunction[]; onSelect: (name: string) => void }) {
  if (items.length === 0) {
    return <EmptyState message="暂无低置信度函数。" />;
  }
  return (
    <section className="panel">
      <h3>低置信度函数</h3>
      <div className="list">
        {items.map((item) => (
          <button className="list-button compact" key={item.canonical_name} onClick={() => onSelect(item.canonical_name)} type="button">
            <strong>{item.canonical_name}</strong>
            <span>{item.summary || "暂无摘要"}</span>
            <small>{item.package_name || "unknown"} · {item.category || "unknown"}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
