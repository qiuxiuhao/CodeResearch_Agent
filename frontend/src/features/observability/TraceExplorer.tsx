import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";
import { getTrace, getTraceEvents, getTraceSpans, listTraces } from "./api";
import type { SpanRecord, TraceDetail, TraceEvent, TraceRecord } from "./types";

type Props = { onClose: () => void };

export function TraceExplorer({ onClose }: Props) {
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [spans, setSpans] = useState<SpanRecord[]>([]);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [selectedSpan, setSelectedSpan] = useState<string | null>(null);
  const [traceType, setTraceType] = useState("");
  const [status, setStatus] = useState("");
  const [live, setLive] = useState(false);
  const [compareId, setCompareId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function refreshList() {
    setError(null);
    try {
      const response = await listTraces({ traceType, status });
      setTraces(response.items);
      if (!selectedId && response.items[0]) setSelectedId(response.items[0].trace_id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Trace 列表加载失败");
    }
  }

  useEffect(() => { void refreshList(); }, [traceType, status]);

  useEffect(() => {
    if (!selectedId) return;
    setSelectedSpan(null);
    Promise.all([getTrace(selectedId), getTraceSpans(selectedId), getTraceEvents(selectedId)])
      .then(([nextDetail, nextSpans, nextEvents]) => {
        setDetail(nextDetail);
        setSpans(nextSpans.items);
        setEvents(nextEvents.items);
        setSelectedSpan(nextDetail.trace.root_span_id);
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Trace 详情加载失败"));
  }, [selectedId]);

  useEffect(() => {
    if (!live || !selectedId) return;
    let active = true;
    const timer = window.setInterval(() => {
      const after = events.reduce((max, item) => Math.max(max, item.stream_sequence ?? 0), 0);
      void getTraceEvents(selectedId, after).then((response) => {
        if (!active) return;
        setEvents((current) => {
          const seen = new Set(current.map((item) => item.stream_sequence ?? item.event_id));
          return [
            ...current,
            ...response.items.filter((item) => !seen.has(item.stream_sequence ?? item.event_id))
          ];
        });
        if (response.items.some((item) => item.name === "trace.terminal")) setLive(false);
      }).catch((exc) => setError(exc instanceof Error ? exc.message : "Trace 事件刷新失败"));
    }, 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [events, live, selectedId]);

  const selected = spans.find((item) => item.span_id === selectedSpan) ?? null;
  const ordered = useMemo(() => treeRows(spans, detail?.trace.root_span_id), [spans, detail]);
  const traceStart = detail ? Date.parse(detail.trace.started_at) : 0;
  const traceDuration = Math.max(detail?.trace.duration_ms ?? 1, 1);
  const compareTrace = traces.find((item) => item.trace_id === compareId);
  const comparison = detail && compareTrace ? comparisonCompatibility(detail.trace, compareTrace) : null;

  return (
    <section className="trace-explorer">
      <header className="trace-explorer-header">
        <button className="secondary-button" onClick={onClose}><ArrowLeft size={16} /> 返回分析</button>
        <div><p className="eyebrow">v1.8 metadata-only</p><h1>Trace Explorer</h1></div>
        <button className="icon-button" onClick={() => void refreshList()} aria-label="刷新 Trace"><RefreshCw size={17} /></button>
      </header>
      {error && <div className="trace-warning"><AlertTriangle size={16} />{error}</div>}
      <div className="trace-layout">
        <aside className="trace-list panel">
          <div className="trace-filters">
            <select aria-label="Trace 类型" value={traceType} onChange={(event) => setTraceType(event.target.value)}>
              <option value="">全部类型</option><option value="api_request">API</option><option value="analysis">Analysis</option>
              <option value="indexing">Index</option><option value="retrieval">Retrieval</option><option value="research_agent">Agent</option><option value="alignment">Alignment</option><option value="evaluation">Evaluation</option>
            </select>
            <select aria-label="Trace 状态" value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">全部状态</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="partial">Partial</option><option value="abandoned">Abandoned</option>
            </select>
          </div>
          {traces.map((trace) => <button key={trace.trace_id} className={`trace-row ${selectedId === trace.trace_id ? "active" : ""}`} onClick={() => setSelectedId(trace.trace_id)}>
            <span><Activity size={14} />{trace.trace_type}</span><small>{trace.status} · {formatDuration(trace.duration_ms)}</small><Completeness trace={trace} />
          </button>)}
        </aside>
        <main className="trace-detail panel">
          {!detail ? <p className="muted">选择一个 Trace 查看调用树。</p> : <>
            <div className="trace-summary">
              <div><strong>{detail.trace.trace_type}</strong><code>{detail.trace.trace_id}</code></div>
              <Completeness trace={detail.trace} />
              <button className="secondary-button" disabled={detail.trace.status !== "running"} onClick={() => setLive((value) => !value)}>{live ? "停止实时" : "实时事件"}</button>
            </div>
            <div className="trace-compare">
              <label>并排比较 <select value={compareId} onChange={(event) => setCompareId(event.target.value)}><option value="">不比较</option>{traces.filter((item) => item.trace_id !== detail.trace.trace_id).map((item) => <option key={item.trace_id} value={item.trace_id}>{item.trace_type} · {item.trace_id.slice(0, 8)}</option>)}</select></label>
              {comparison && <span className={`trace-completeness ${comparison === "compatible" ? "complete" : "partial"}`}>{comparison}{comparison !== "compatible" ? "：仅并排展示，不声明性能回归" : ""}</span>}
            </div>
            {detail.trace.completeness !== "complete" && <div className="trace-integrity"><AlertTriangle size={16} /><span>此调用链不完整：{detail.trace.integrity_flags.join(", ") || "unknown completeness"}。不得据此推导精确业务结论。</span></div>}
            <div className="waterfall" role="tree" aria-label="Span 调用树">
              {ordered.map(({ span, depth }) => {
                const offset = Math.max(0, Date.parse(span.started_at) - traceStart);
                const left = Math.min(98, (offset / traceDuration) * 100);
                const width = Math.max(0.6, Math.min(100 - left, ((span.duration_ms ?? 0.1) / traceDuration) * 100));
                return <button role="treeitem" key={span.span_id} className={`waterfall-row ${selectedSpan === span.span_id ? "active" : ""}`} onClick={() => setSelectedSpan(span.span_id)}>
                  <span className="span-name" style={{ paddingLeft: `${depth * 16 + 8}px` }}>{span.name}</span>
                  <span className="span-track"><i style={{ left: `${left}%`, width: `${width}%` }} /></span><small>{formatDuration(span.duration_ms)}{span.duration_estimated ? " est." : ""}</small>
                </button>;
              })}
            </div>
            <div className="trace-bottom-grid">
              <section><h2>Span Detail</h2>{selected ? <><p><code>{selected.span_id}</code></p><p>{selected.component} · {selected.status}</p>{selected.error_message_template && <p className="danger">{selected.exception_type}: {selected.error_message_template}</p>}<pre>{JSON.stringify(selected.attributes, null, 2)}</pre></> : <p className="muted">未选择 Span</p>}</section>
              <section><h2>Events</h2><div className="event-list">{events.map((event) => <div key={event.event_id}><strong>#{event.stream_sequence} {event.name}</strong><small>{event.severity} · {new Date(event.occurred_at).toLocaleTimeString()}</small></div>)}</div></section>
              <section><h2>Links / Evidence</h2>{detail.links.map((link) => <p key={link.link_id}><code>{link.relation}</code> → {link.linked_trace_id.slice(0, 12)}…</p>)}{detail.artifacts.map((artifact) => <p key={artifact.ref_id}><code>{artifact.artifact_type}</code> {artifact.role}: {artifact.artifact_id}</p>)}</section>
            </div>
          </>}
        </main>
      </div>
    </section>
  );
}

function Completeness({ trace }: { trace: TraceRecord }) {
  return <span className={`trace-completeness ${trace.completeness}`}>{trace.completeness === "complete" ? "complete" : trace.completeness === "partial" ? "partial telemetry" : "unknown completeness"}</span>;
}

function formatDuration(value?: number | null) { return value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${value.toFixed(1)}ms`; }

function treeRows(spans: SpanRecord[], rootId?: string) {
  const children = new Map<string | null, SpanRecord[]>();
  spans.forEach((span) => { const key = span.parent_span_id && spans.some((item) => item.span_id === span.parent_span_id) ? span.parent_span_id : null; children.set(key, [...(children.get(key) ?? []), span]); });
  const output: Array<{ span: SpanRecord; depth: number }> = [];
  const visit = (span: SpanRecord, depth: number) => { output.push({ span, depth }); (children.get(span.span_id) ?? []).forEach((child) => visit(child, depth + 1)); };
  const root = spans.find((span) => span.span_id === rootId);
  if (root) visit(root, 0);
  (children.get(null) ?? []).filter((span) => span.span_id !== rootId).forEach((span) => visit(span, 0));
  return output;
}

function comparisonCompatibility(left: TraceRecord, right: TraceRecord) {
  if (left.completeness !== "complete" || right.completeness !== "complete") return "incompatible";
  if (left.attribute_registry_version !== right.attribute_registry_version || left.operation_taxonomy_version !== right.operation_taxonomy_version) return "incompatible";
  for (const key of ["cra.graph.version", "cra.model.profile", "cra.scorer.profile"]) {
    if (left.attributes[key] !== right.attributes[key]) return "partially_compatible";
  }
  if (left.recording_mode !== right.recording_mode || left.trace_type !== right.trace_type) return "partially_compatible";
  return "compatible";
}
