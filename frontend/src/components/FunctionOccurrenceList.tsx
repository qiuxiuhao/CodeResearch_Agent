import type { LibraryFunctionOccurrence } from "../types/analysis";
import { EmptyState } from "./EmptyState";

export function FunctionOccurrenceList({ occurrences }: { occurrences: LibraryFunctionOccurrence[] }) {
  if (occurrences.length === 0) {
    return <EmptyState message="暂无出现历史。" />;
  }
  return (
    <div className="occurrence-list">
      {occurrences.map((item) => (
        <article className="item-card" key={`${item.id}-${item.task_id}-${item.file_path}-${item.line_no}`}>
          <h4>{item.task_id}</h4>
          <p>{item.project_name || "未知项目"} · {item.file_path}</p>
          <p>{item.qualified_function_name}{item.line_no ? ` · 行 ${item.line_no}` : ""}</p>
          <pre>{item.call_text}</pre>
          <p className="muted">{item.created_at || "未知时间"}</p>
        </article>
      ))}
    </div>
  );
}
