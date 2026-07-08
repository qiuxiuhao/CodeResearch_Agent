import type { GlobalLibraryFunction } from "../types/analysis";
import { EmptyState } from "./EmptyState";

type Props = {
  items: GlobalLibraryFunction[];
  selectedName?: string | null;
  onSelect: (canonicalName: string) => void;
};

export function GlobalLibraryList({ items, selectedName, onSelect }: Props) {
  if (items.length === 0) {
    return <EmptyState message="暂无全局函数库记录，请先运行一次代码分析任务。" />;
  }
  return (
    <div className="list global-library-list">
      {items.map((item) => (
        <button
          className={`list-button ${selectedName === item.canonical_name ? "active" : ""}`}
          key={item.canonical_name}
          onClick={() => onSelect(item.canonical_name)}
          type="button"
        >
          <strong>{item.canonical_name}</strong>
          <span>{item.summary || "暂无摘要"}</span>
          <small>
            {item.package_name || "unknown"} · {item.category || "unknown"} · {item.confidence || "medium"}
          </small>
        </button>
      ))}
    </div>
  );
}
