import type { AnalysisResult, LibraryCall, Mode, ResultTab } from "../types/analysis";
import { DiagramsPanel } from "./DiagramsPanel";
import { FileAnalysisPanel } from "./FileAnalysisPanel";
import { FunctionAnalysisPanel } from "./FunctionAnalysisPanel";
import { GlobalLibraryPanel } from "./GlobalLibraryPanel";
import { LibraryDocsPanel } from "./LibraryDocsPanel";
import { ModelAnalysisPanel } from "./ModelAnalysisPanel";
import { PaperAnalysisPanel } from "./PaperAnalysisPanel";
import { SummaryCards } from "./SummaryCards";
import { EmptyState } from "./EmptyState";

const TABS: Array<[ResultTab, string]> = [
  ["overview", "总览"],
  ["files", "文件"],
  ["functions", "函数"],
  ["libraries", "库函数"],
  ["globalLibrary", "全局函数库"],
  ["models", "模型"],
  ["paper", "论文"],
  ["diagrams", "图示"],
  ["report", "报告"]
];

type Props = {
  activeTab: ResultTab;
  mode: Mode;
  result: AnalysisResult | null;
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
      {activeTab === "globalLibrary" && <GlobalLibraryPanel />}
      {activeTab !== "globalLibrary" && !result && (
        <section className="hero-panel">
          <h1>CodeResearch Agent</h1>
          <p>创建一个分析任务，查看代码结构、函数逻辑、模型网络、论文对齐和 Mermaid 图示。</p>
          <EmptyState message="也可以直接打开“全局函数库”查看已沉淀的库函数知识。" />
        </section>
      )}
      {result && activeTab === "overview" && <SummaryCards result={result} />}
      {result && activeTab === "files" && <FileAnalysisPanel result={result} />}
      {result && activeTab === "functions" && <FunctionAnalysisPanel mode={mode} result={result} onLibraryCallClick={onLibraryCallClick} />}
      {result && activeTab === "libraries" && <LibraryDocsPanel result={result} />}
      {result && activeTab === "models" && <ModelAnalysisPanel result={result} />}
      {result && activeTab === "paper" && <PaperAnalysisPanel result={result} />}
      {result && activeTab === "diagrams" && <DiagramsPanel result={result} />}
      {result && activeTab === "report" && (
        <section className="tab-content">
          <h2>报告</h2>
          <pre>{result.report_md || "暂无报告"}</pre>
        </section>
      )}
    </>
  );
}
