import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, RefreshCw } from "lucide-react";
import { listBadCases, listBaselines, listComparisons, listEvaluationDatasets, listEvaluationRuns } from "./api";
import type { BadCase, BaselineBinding, Comparison, EvaluationDataset, EvaluationRun } from "./types";

type Props = { onClose: () => void };

export function EvaluationDashboard({ onClose }: Props) {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [baselines, setBaselines] = useState<BaselineBinding[]>([]);
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [badCases, setBadCases] = useState<BadCase[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [badCaseStatus, setBadCaseStatus] = useState("");

  async function refresh() {
    setError(null);
    try {
      const [runData, datasetData, baselineData, comparisonData, badCaseData] = await Promise.all([
        listEvaluationRuns(), listEvaluationDatasets(), listBaselines(), listComparisons(), listBadCases(badCaseStatus)
      ]);
      setRuns(runData.items); setDatasets(datasetData.items); setBaselines(baselineData.items);
      setComparisons(comparisonData.items); setBadCases(badCaseData.items);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Evaluation Dashboard 加载失败");
    }
  }

  useEffect(() => { void refresh(); }, [badCaseStatus]);

  return <section className="evaluation-dashboard">
    <header className="trace-explorer-header">
      <button className="secondary-button" onClick={onClose}><ArrowLeft size={16} /> 返回分析</button>
      <div><p className="eyebrow">v1.9 deterministic-first</p><h1>Evaluation Dashboard</h1></div>
      <button className="icon-button" onClick={() => void refresh()} aria-label="刷新 Evaluation"><RefreshCw size={17} /></button>
    </header>
    {error && <div className="trace-warning"><AlertTriangle size={16} />{error}</div>}
    <div className="evaluation-summary-grid">
      <Summary label="Frozen datasets" value={datasets.length} />
      <Summary label="Completed runs" value={runs.filter((run) => run.status === "completed").length} />
      <Summary label="Active baselines" value={baselines.filter((item) => item.status === "active").length} />
      <Summary label="Open bad cases" value={badCases.filter((item) => !["closed", "rejected"].includes(item.status)).length} />
    </div>
    <div className="evaluation-grid">
      <section className="panel"><h2>Evaluation Runs</h2>{runs.length ? runs.map((run) => <article className="evaluation-row" key={run.run_id}>
        <div><strong>{run.mode}</strong><code>{run.run_id}</code></div><Status value={run.status} />
        <small>{run.dataset_version_id} · {run.case_counts.completed ?? 0}/{run.case_counts.total ?? 0} cases</small>
      </article>) : <p className="muted">暂无 Evaluation Run</p>}</section>
      <section className="panel"><h2>Datasets / Baselines</h2>{datasets.map((dataset) => <article className="evaluation-row" key={dataset.dataset_id}><div><strong>{dataset.name}</strong><small>{dataset.component_scope.join(" · ")}</small></div><Status value={dataset.status} /></article>)}
        {baselines.map((binding) => <article className="evaluation-row" key={binding.baseline_binding_id}><div><strong>{binding.component} baseline</strong><code>{binding.baseline_run_id}</code></div><Status value={binding.status} /></article>)}</section>
      <section className="panel"><h2>Comparisons / Gates</h2>{comparisons.length ? comparisons.map((comparison) => <article className="evaluation-row" key={comparison.comparison_id}><div><strong>{comparison.scope.compatibility}</strong><small>{comparison.scope.common_case_ids.length} common cases</small></div><Status value={comparison.status} />{comparison.scope.incompatibility_reasons.length > 0 && <small>{comparison.scope.incompatibility_reasons.join(", ")}</small>}</article>) : <p className="muted">暂无 Baseline Comparison</p>}</section>
      <section className="panel"><div className="evaluation-section-heading"><h2>Bad Cases</h2><select aria-label="Bad Case 状态" value={badCaseStatus} onChange={(event) => setBadCaseStatus(event.target.value)}><option value="">全部</option><option value="open">Open</option><option value="confirmed">Confirmed</option><option value="fixed">Fixed</option><option value="verified">Verified</option></select></div>
        {badCases.length ? badCases.map((item) => <article className="evaluation-row" key={item.bad_case_id}><div><strong>{item.symptom}</strong><small>{item.component} · {item.confirmed_root_cause ?? "root cause pending"} · {item.occurrence_count} occurrence(s)</small>{item.source_trace_id && <a href={`#trace-${item.source_trace_id}`}>Trace {item.source_trace_id.slice(0, 10)}…</a>}</div><Status value={item.status} /></article>) : <p className="muted">暂无 Bad Case</p>}</section>
    </div>
    <div className="trace-integrity"><AlertTriangle size={16} /><span>Alignment human Gold remains <code>ALIGNMENT_BENCHMARK_PENDING</code>. Synthetic CI cases validate contracts only.</span></div>
  </section>;
}

function Summary({ label, value }: { label: string; value: number }) { return <div className="panel evaluation-summary"><strong>{value}</strong><span>{label}</span></div>; }
function Status({ value }: { value: string }) { const good = ["completed", "active", "ready", "passed", "verified", "closed", "frozen"].includes(value); return <span className={`evaluation-status ${good ? "good" : "neutral"}`}>{good && <CheckCircle2 size={13} />}{value}</span>; }
