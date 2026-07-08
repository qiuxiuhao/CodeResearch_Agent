import { useMemo, useState } from "react";
import type { AnalysisResult, LibraryCall, Mode } from "../types/analysis";
import { EmptyState } from "./EmptyState";
import { FunctionDetail } from "./FunctionDetail";

type Props = {
  result: AnalysisResult;
  mode: Mode;
  onLibraryCallClick: (call: LibraryCall) => void;
};

export function FunctionAnalysisPanel({ result, mode, onLibraryCallClick }: Props) {
  const functions = result.function_analysis?.function_analysis ?? [];
  const [selectedName, setSelectedName] = useState<string | null>(functions[0]?.qualified_name ?? null);
  const selected = useMemo(
    () => functions.find((fn) => fn.qualified_name === selectedName) ?? functions[0],
    [functions, selectedName]
  );

  if (functions.length === 0) {
    return <EmptyState message="暂无函数级分析。" />;
  }

  return (
    <section className="tab-content">
      <h2>函数级分析</h2>
      <div className="split">
        <div className="list">
          {functions.map((fn) => (
            <button
              className={`list-button ${selected?.qualified_name === fn.qualified_name ? "active" : ""}`}
              key={fn.qualified_name}
              onClick={() => setSelectedName(fn.qualified_name ?? null)}
            >
              <strong>{fn.qualified_name || fn.function_name}</strong>
              <small>{fn.file_path}</small>
            </button>
          ))}
        </div>
        {selected && <FunctionDetail fn={selected} mode={mode} onLibraryCallClick={onLibraryCallClick} />}
      </div>
    </section>
  );
}
