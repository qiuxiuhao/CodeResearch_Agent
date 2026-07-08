import type { GlobalLibraryFunction } from "../types/analysis";
import { EmptyState } from "./EmptyState";

export function HighFrequencyFunctions({ items, onSelect }: { items: GlobalLibraryFunction[]; onSelect: (name: string) => void }) {
  if (items.length === 0) {
    return <EmptyState message="暂无高频函数。" />;
  }
  return (
    <section className="panel">
      <h3>高频函数</h3>
      <div className="list">
        {items.map((item) => (
          <button className="list-button compact" key={item.canonical_name} onClick={() => onSelect(item.canonical_name)} type="button">
            <strong>{item.canonical_name}</strong>
            <small>出现 {item.occurrence_count ?? 0} 次 · {item.package_name || "unknown"}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
