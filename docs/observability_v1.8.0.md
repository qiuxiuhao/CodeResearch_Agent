# v1.8.0 统一 Trace 与可观测性

v1.8.0 提供 metadata-only 的 Trace、Span、Event、Link、ArtifactRef、Metrics、SSE 和 Trace Explorer。Trace 是可删除的诊断派生数据；Research/Alignment Run Store 仍是业务控制平面，LangGraph Checkpointer 仍是恢复状态源。

## 启用

默认 Recorder 和读取 API 均关闭：

```bash
export OBSERVABILITY_ENABLED=true
export OBSERVABILITY_API_ENABLED=true
export OBSERVABILITY_DB_PATH=data/observability.sqlite3
```

读取 API 在当前无正式认证的部署中只允许本机管理员。客户端 Header、caller scope hash、`traceparent` 和 `tracestate` 都不是授权证明。

常用配置：

```text
OBSERVABILITY_REMOTE_PARENT_MODE=link
OBSERVABILITY_HTTP_INSTRUMENTATION=manual
OBSERVABILITY_DIAGNOSTIC_SAMPLE_RATE=0
OBSERVABILITY_OTLP_ENABLED=false
OBSERVABILITY_OTLP_SAMPLE_RATE=0
OBSERVABILITY_RETENTION_SECONDS=1209600
OBSERVABILITY_QUEUE_SIZE=4096
OBSERVABILITY_BATCH_SIZE=128
OBSERVABILITY_FLUSH_INTERVAL_SECONDS=0.25
```

外部 OTLP HTTP 需要可选依赖 `pip install -e '.[observability]'` 和显式 endpoint。OTel Adapter 只从 Internal Recorder 单向导出，不回写本地 SQLite。

## 隐私边界

v1.8 不支持 Content Capture。Query、Prompt、模型 Response、代码、论文正文、上传内容、Authorization、Cookie、Secret、Connection String、原始异常文本、完整 State 和 Checkpoint Blob 均不得进入 Trace DB。

需要定位原始业务对象时只保存 `TraceArtifactRef`，并由原业务 API 独立授权读取。异常只保存稳定 error code、异常类、安全模板和可选 HMAC；HMAC Key 本身不落库。

## 生命周期与完整性

Internal Recorder 通过幂等 `TelemetryCommand` 写入有界队列。SQLite single writer 分配 Trace 内单调 `stream_sequence`，SSE 使用该序号作为 `Last-Event-ID`。重复 command 不会重复应用，终态不可逆转，崩溃后未结束 Span 会标为 abandoned。

`complete` 表示正常 Root 结束且没有完整性标记；Queue drop、Store failure、缺失 start/end、crash、sequence gap、orphan 或 export incomplete 会产生 `partial`/`unknown`。不完整 Trace 和聚合结果不能作为精确业务事实。

## API

```text
GET /observability/traces
GET /observability/traces/{trace_id}
GET /observability/traces/{trace_id}/spans
GET /observability/traces/{trace_id}/spans/{span_id}
GET /observability/traces/{trace_id}/events
GET /observability/traces/{trace_id}/events/stream
GET /observability/metrics/summary
GET /observability/metrics/timeseries
```

Span ID 只在 Trace 内唯一，详情必须同时提供 `trace_id + span_id`。所有列表有分页、数量和响应大小限制；SSE 断开不取消业务 Run。

## 验证

```bash
python -m pytest -q tests/observability
python scripts/benchmark_observability.py
npm --prefix frontend test
npm --prefix frontend run build
bash scripts/validate.sh
```

自动测试使用本地 InMemory/SQLite Sink，不访问网络，不发送 OTLP。

## v1.8.0 验收结果

2026-07-18 在 `code-research-agent` Conda Python 3.11 环境执行：

- `python -m pytest -q tests/observability`：30 passed。
- `bash scripts/validate.sh`：后端 373 passed；前端 17 个测试文件、30 项测试通过；TypeScript typecheck、Vite production build 与 build contract 通过。
- `python scripts/benchmark_observability.py --iterations 2000`：Noop 调用 P95 0.0003 ms；metadata enqueue P95 0.0875 ms；实测 26,859.66 commands/s。
- `git diff --check`：通过。

上述性能是当前本机的开发验收数据，不是跨机器 SLA。v1.7 功能实现已经形成基线，但真实 Alignment Gold 质量评测仍标记为 `ALIGNMENT_BENCHMARK_PENDING`；Trace 运行指标不得被解释为 Alignment Accuracy、F1 或 Calibration 质量。
