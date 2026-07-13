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
  const [selectedKey, setSelectedKey] = useState<string | null>(functions[0] ? functionKey(functions[0]) : null);
  const selected = useMemo(
    () => functions.find((fn) => functionKey(fn) === selectedKey) ?? functions[0],
    [functions, selectedKey]
  );
  const explanation = result.llm_explanations?.function_explanations?.find(
    (item) => item.qualified_name === selected?.qualified_name && item.file_path === selected?.file_path
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
              className={`list-button ${selected && functionKey(selected) === functionKey(fn) ? "active" : ""}`}
              key={functionKey(fn)}
              onClick={() => setSelectedKey(functionKey(fn))}
            >
              <strong>{fn.qualified_name || fn.function_name}</strong>
              <small>{fn.file_path}</small>
            </button>
          ))}
        </div>
        {selected && <FunctionDetail fn={selected} mode={mode} explanation={explanation} onLibraryCallClick={onLibraryCallClick} />}
      </div>
    </section>
  );
}

function functionKey(fn: { file_path?: string; qualified_name?: string }): string {
  return `${fn.file_path ?? ""}:${fn.qualified_name ?? ""}`;
}
