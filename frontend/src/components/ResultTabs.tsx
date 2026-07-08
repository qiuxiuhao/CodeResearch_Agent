import type { AnalysisResult, LibraryCall, Mode, ResultTab } from "../types/analysis";
import { DiagramsPanel } from "./DiagramsPanel";
import { FileAnalysisPanel } from "./FileAnalysisPanel";
import { FunctionAnalysisPanel } from "./FunctionAnalysisPanel";
import { LibraryDocsPanel } from "./LibraryDocsPanel";
import { ModelAnalysisPanel } from "./ModelAnalysisPanel";
import { PaperAnalysisPanel } from "./PaperAnalysisPanel";
import { SummaryCards } from "./SummaryCards";

const TABS: Array<[ResultTab, string]> = [
  ["overview", "总览"],
  ["files", "文件"],
  ["functions", "函数"],
  ["libraries", "库函数"],
  ["models", "模型"],
  ["paper", "论文"],
  ["diagrams", "图示"],
  ["report", "报告"]
];

type Props = {
  activeTab: ResultTab;
  mode: Mode;
  result: AnalysisResult;
  onTabChange: (tab: ResultTab) => void;
  onLibraryCallClick: (call: LibraryCall) => void;
};

export function ResultTabs({ activeTab, mode, result, onTabChange, onLibraryCallClick }: Props) {
  return (
    <>
      <nav className="tabs" aria-label="分析结果导航">
        {TABS.map(([tab, label]) => (
          <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => onTabChange(tab)}>
            {label}
          </button>
        ))}
      </nav>
      {activeTab === "overview" && <SummaryCards result={result} />}
      {activeTab === "files" && <FileAnalysisPanel result={result} />}
      {activeTab === "functions" && <FunctionAnalysisPanel mode={mode} result={result} onLibraryCallClick={onLibraryCallClick} />}
      {activeTab === "libraries" && <LibraryDocsPanel result={result} />}
      {activeTab === "models" && <ModelAnalysisPanel result={result} />}
      {activeTab === "paper" && <PaperAnalysisPanel result={result} />}
      {activeTab === "diagrams" && <DiagramsPanel result={result} />}
      {activeTab === "report" && (
        <section className="tab-content">
          <h2>报告</h2>
          <pre>{result.report_md || "暂无报告"}</pre>
        </section>
      )}
    </>
  );
}
