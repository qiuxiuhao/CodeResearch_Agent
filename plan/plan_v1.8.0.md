# CodeResearch Agent v1.8.0：统一 Trace 与可观测性系统开发计划

状态：v1.7 实现基线验收、实际代码审计与 v1.8 开工前设计冻结

事实基线：分支 `upgrade/v1.7-paper-code-alignment`，Commit `25edd020e533baa90bee432f4a6251fc0fac531b`，HEAD 无 tag

v1.7 质量债务：`ALIGNMENT_BENCHMARK_PENDING`

实施范围：v1.8.0-a、b、c1～c3、d 至 f

## 0. 开工前置条件

1. v1.8 实施必须固定上述 v1.7 Commit；若实施前 HEAD 变化，重新执行完整基线验收并更新 SHA。
2. 建议先给已验收 Commit 创建受保护的 `v1.7.0` tag；本轮不创建 tag 或 commit。
3. v1.7 状态必须严格表述为：`implementation complete`，但 `alignment quality benchmark pending`。当前 Alignment Benchmark 没有真实 gold case，稳定技术债标识为 `ALIGNMENT_BENCHMARK_PENDING`；因此 v1.7 不能被描述为满足了全部质量 Definition of Done。
4. 实施前固定受支持 Python 环境；当前 shell Python 3.13.13 缺 pytest，项目 `scripts/validate.sh` 在 Conda Python 3.11.15 下通过 343 个后端测试、29 个前端测试和 build。
5. 所有 Trace 功能必须可以切换为 Noop，且不得改变业务状态、排序、恢复、证据或回答。
6. `ALIGNMENT_BENCHMARK_PENDING` 不阻塞 v1.8 Trace 基础设施实施，因为本阶段验收的是插桩正确性、隐私、完整性、故障隔离和性能；不得用 Trace count、latency、accepted rate 等运行指标推造 Alignment Accuracy、F1、Calibration 或其他质量结果。
7. 真实 Alignment Gold 最迟在 v1.9 Evaluation/Bad Case 阶段补齐，并以独立人工 Gold、Locked Test 与版本化评测报告关闭该技术债。

## 1. 背景与目标

v1.4 至 v1.7 已分别建立结构化索引、Hybrid Retrieval、动态 Research Agent 和论文代码对齐。v1.7 正式功能实现与合同测试已经完成，但 Alignment 真实质量 Benchmark 仍为 `ALIGNMENT_BENCHMARK_PENDING`。现有系统已有 run/version/generation、阶段 latency、Provider token、Tool Observation、Lease、Checkpoint 和错误码，但这些信息分散在业务对象中，没有统一调用树、时间线、跨组件上下文、隐私策略、存储、实时事件或查询界面。

v1.8 建立独立的 metadata-first 可观测层：统一 Trace/Span/Event/Link/Artifact/Metrics 合同，用轻量 Recorder 连接 API、Analysis、Index、Retrieval、Agent、Alignment、Provider、Tool、DB、Cache 和 Checkpoint；通过独立 SQLite Store、受限 API、SSE 与 Trace Explorer 展示运行，不把 Trace 变成业务事实或恢复机制。

成功标准是：业务行为不变的前提下，可以按 request/run/repo/index version 重建时间线、定位错误和降级、解释 Token/预算/证据流，并保证默认不保存敏感原文、可观测性故障不增加业务失败率。

## 2. 当前代码事实与可插桩点

### 2.1 API 与请求

| 入口 | 当前事实 | 可用属性/敏感性 | 建议 Span |
| -- | -- | -- | -- |
| `backend/app/main.py::app` | 只有 CORS middleware；lifespan 管理 Analysis executor、Research/Alignment Coordinator | method、route template、status、duration；header/body 敏感 | Root `api.request` |
| `main.py::_run_background_analysis` | ThreadPoolExecutor 后台 Analysis；进程内进度与错误字符串 | task_id、status；不得保存上传内容 | 新 `analysis` Trace，以 Link 关联入队 API |
| Research API `_caller_scope` | header 或 client host；不是正式认证 | 只存 caller scope hash | API root 属性 |
| Alignment API `_caller_scope` | header 或 anonymous，规则与 Research 不完全一致 | 只存 hash | API root 属性 |
| API error helpers | 新 API 有结构化 error 且 `trace_id=None`；旧接口多为 `HTTPException` | error code/status，可保存脱敏 message | `exception` Event + root status |

客户端不能借 Trace Context 控制授权或业务身份。v1.8 middleware 验证标准远端上下文，再按 `continue|link|ignore` 配置处理；首版默认 `link`，由服务端创建本地 Trace ID。响应可回显服务端 `X-Request-ID` 与实际本地 Trace ID。

### 2.2 Analysis Graph

`backend/app/agents/graph.py::build_analysis_graph` 构造 22 个确定性 Node。`_wrap_progress_node` 已有 start/finish/error 边界，适合创建 `analysis.node` Child Span；`_notify_progress` 当前吞掉 callback 错误，Recorder 也必须遵循同样的非阻断原则。

`backend/app/services/task_progress.py::AnalysisProgressStore` 只保存 task_id、状态、时间、当前节点、百分比、错误和摘要，并显式不保存完整 State。它不是 Trace Store。可记录 node name、status、duration、Provider 调用数和输出 artifact ref，不记录完整 State、上传文件、代码或论文内容。

### 2.3 Structured Index

`backend/app/indexing/index_service.py::build_structured_index` 负责 fingerprint、artifact 构建、staging、持久化、校验、ready/active 与 manifest。`backend/app/persistence/index_store.py::StructuredIndexStore` 管理 SQLite 状态机、Lease、短事务和 active version；`001_structured_index.sql` 是事实库 migration。

独立且无本地 parent时创建 `indexing.build` Root；从 Analysis或其他业务上下文调用时创建同名 Child Span，不得另建Trace。其下为 `indexing.fingerprint`、`indexing.entities`、`indexing.edges`、`indexing.evidence`、`indexing.chunks`、`database.persist_index`、`indexing.validate`、`indexing.activate` 和 `indexing.manifest`。属性只含 repo/version/schema、计数、hash、lease/retry/status，不含源码文本。

### 2.4 Retrieval

`backend/app/retrieval/service.py::RetrievalService.search` 的真实顺序是：

```text
Sparse + Dense
→ Preliminary RRF
→ Graph Expansion
→ Final RRF
→ Reranker Fusion
→ Evidence/Public Candidate
```

它已记录 profile、vector sync、FTS sync、Sparse、Dense、Preliminary RRF、Graph、Final RRF/Reranker 和 total latency。独立调用且无本地 parent时 `retrieval.search` 是Root；Agent、Alignment、Analysis或API Service内调用时它是Child。其下可直接映射 `retrieval.fts_sync`、`vector_sync`、`sparse`、`dense`、`preliminary_rrf`、`graph`、`final_rrf`、`rerank`、`context.build`、`citation.validate`。

FTS Generation 与 Vector Manifest 已有 building/ready/failed/stale/superseded 状态、generation/profile hash、计数和版本隔离。Trace 保存 generation ID、model/profile hash、counts、fallback 和 warning code，不复制 query、candidate text 或 ContextBundle text。

### 2.5 Research Agent

- `backend/app/agents/research/schemas.py::ResearchState` 包含 query、plan、observations、context、answer、budget 和运行状态；不得整体写入 Trace。
- `ToolExecutionContext` 已有 `trace_id`、run/repo/version/cancel check，是 Tool Context 传播入口。
- Tool Registry/Executor 已记录 latency、status、error code、semantic `tool_call_key`、reuse、result IDs/count。
- Research Graph 包含 route、direct retrieve、plan/validate/bind、execute、assess、replan、context、answer、citation、claim 和 finalizer 节点。
- `ResearchRunStore` 是 run/idempotency/cancel/lease/plan/terminal 控制面。
- `ResearchCheckpointRuntime` 使用独立 SQLite Checkpointer，负责 State/恢复/Interrupt。
- Coordinator 使用受控 tasks、Lease、recovery/resume/cancel，并在内部消费 LangGraph `astream`；当前没有公开事件流。

建议 Root `agent.run`，Child 为 `agent.route`、`agent.direct_retrieve`、`agent.plan`、`agent.validate_plan`、`agent.resolve_arguments`、`tool.execute`、`agent.assess_evidence`、`agent.replan`、`checkpoint.write/read`、`agent.context`、`provider.generate`、`agent.citation_validate`、`agent.claim_verify`、`agent.finalize`。Resume、Retry、Tool reuse 使用 Link，而不是伪造 Parent。

### 2.6 Alignment

`AlignmentService.process_run` 实际执行 profiling、recalling、featurizing、scoring、optional verifying、ready/activate；每阶段在 Store 中短事务持久化。Coordinator 有 managed task、Lease/heartbeat、recovery/cancel/shutdown。Store 是独立 `paper_code_alignment.sqlite3`，包含 Run、stage manifest、Deployment、Review 等。

建议 Root `alignment.run`，Child 为 `alignment.profile`、`candidate_recall`、`feature_extract`、`score`、`calibrate`、`set_decision`、`verify`、`database.persist_stage`、`activate`、`review`。只存 profile/candidate/decision counts、类型、模型配置 hash、fallback、authority 和 Evidence ID 引用，不存论文/代码内容。

### 2.7 Provider、Cache、Token、Cost 与隐私

`backend/app/services/provider_runtime.py::ModelRouter.generate_structured` 已有 sanitize/redact、input hash、cache、Provider fallback/retry、预算、Schema/Evidence validation 和 metadata；Provider adapter 记录 latency/token。Cache 中保存完整结构化业务响应是既有职责，Trace 只能记录 cache hit/miss、key hash、size 和 latency。

Provider Span 可记录 provider/model/revision、prompt version、attempt、fallback、timeout、input/output token、cache status、consent decision 和 validation status。当前没有稳定货币价格表；`estimated_cost` 未知时必须为 null，只有版本化 pricing profile 才能计算。

### 2.8 当前日志、计时、错误与流

- 没有统一结构化日志；少量模块使用 Python logging，部分 CLI 直接输出摘要。
- Retrieval、Tool 和 Provider 有局部计时；Analysis/Index/Alignment 没有统一阶段计时。
- 错误码存在于各 API/Store/Tool，但未映射到统一 Span status。
- `trace_id` 响应字段尚无真实值。
- LangGraph streaming 只在 Coordinator 内部使用；没有 SSE/EventSource 实现。

## 3. 本阶段目标与非目标

### 3.1 目标

1. 严格 Trace/Span/Event/Link/Artifact/Metric/Export Schema。
2. 内部 Attribute Registry、Redactor、Sampler 和 Noop/InMemory Recorder。
3. 异步有界 Recorder 与独立 SQLite Trace Store。
4. API、Analysis、Index、Retrieval、Agent、Alignment、Provider/Tool/DB/Cache/Checkpoint 插桩。
5. 可选 OpenTelemetry Adapter、OTLP HTTP Exporter 和 Metrics。
6. 受权 Trace API、SSE 和最小 Trace Explorer。
7. Retention、失败隔离、性能与完整回归。

### 3.2 非目标

- 不用 Trace 替代 Run Store、Checkpoint、事实库、Retrieval generation 或 Alignment Store。
- 不保存或重放完整 ResearchState、Checkpoint、Prompt、Response、代码或论文正文。
- 不自动重新执行历史 Run，不做自动 Bad Case 回归。
- 不补写或替代 v1.7 Alignment Gold Benchmark；Trace 只能记录运行事实，不能生成或推断 Accuracy、F1、Calibration Gold。该技术债由最迟 v1.9 的 Evaluation/Bad Case 阶段关闭。
- 不强制 LangSmith、Jaeger、Grafana、OTLP Collector 或外部 SaaS。
- 不修改 Retrieval 排序、Agent 决策、Alignment 算法、Provider 选择或业务错误语义。
- 不实现长期日志归档、分布式消息队列、PostgreSQL、Redis 或 Celery。

## 4. Run Store、Checkpoint 与 Trace 边界

```text
ResearchRunStore / AlignmentStore
= 业务状态、Idempotency、Cancel、Lease、终态与版本

LangGraph Checkpointer
= ResearchState、节点 checkpoint、Interrupt 与恢复

Trace Store
= 调用树、时间线、延迟、错误、Token、费用、预算、
  Evidence 引用、降级、重试、复用和导出状态
```

业务 Store 是状态权威源；Checkpoint 是 Graph 执行状态源；Trace 是 best-effort 诊断记录。Trace 不参与业务 commit，不用于恢复，不因缺 Span 改变 Run 状态。Checkpoint Blob 不能由 Trace API读取或复制；Trace 仅保存 checkpoint ID/hash、operation、latency、status 的 ArtifactRef/Event。

若业务状态与 Trace 不一致，以业务 Store 为准并产生 `cra.observability.inconsistency` 指标；不得回写业务事实。Trace 失败只能记录内存 failure counter 或 stderr 的最小脱敏告警。

## 5. Trace、Command 与状态 Schema

新增 `backend/app/observability/schemas.py`。全部模型使用 Pydantic v2、`extra="forbid"`、受限 `JsonValue`、显式 schema version、UTC wall-clock 时间、状态与大小校验，不接收 callable、Provider、连接、任意 State 或自定义对象。v1.8 第一版只支持 `none|metadata|diagnostic_metadata`，不支持原始 Content Capture。

```python
TraceType = Literal[
    "api_request", "analysis", "indexing", "retrieval",
    "research_agent", "alignment",
]
SpanComponent = Literal[
    "api", "analysis_graph", "indexing", "retrieval", "agent",
    "alignment", "provider", "tool", "database", "checkpoint", "cache",
]
RecordingMode = Literal["none", "metadata", "diagnostic_metadata"]

class RecordingDecision(BaseModel):
    record_metadata: bool
    record_diagnostics: bool
    export_otlp: bool
    reason_codes: list[str] = Field(default_factory=list)

class TraceContext(BaseModel):
    schema_version: str
    trace_id: str                 # 32 lowercase hex
    span_id: str                  # 16 lowercase hex
    trace_flags: int              # 仅 W3C/OTel propagation flags
    tracestate: str | None
    request_id: str | None
    trace_type: TraceType
    run_id: str | None
    task_id: str | None
    repo_id: str | None
    index_version_id: str | None
    caller_scope_hash: str | None # 仅关联，不是授权证明
    recording: RecordingDecision

class TraceRecord(BaseModel):
    schema_version: str
    trace_id: str
    trace_type: TraceType
    root_span_id: str
    request_id: str | None
    run_id: str | None
    task_id: str | None
    repo_id: str | None
    index_version_id: str | None
    caller_scope_hash: str | None
    status: Literal["running", "completed", "partial", "failed", "cancelled", "abandoned"]
    lifecycle_version: int
    last_command_id: str | None
    completion_status: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: float | None
    duration_estimated: bool
    recording_mode: RecordingMode
    diagnostic_sampled: bool
    otlp_sampled: bool
    completeness: Literal["complete", "partial", "unknown"]
    integrity_flags: list[Literal[
        "missing_root_start", "missing_root_end", "missing_span_start",
        "missing_span_end", "sequence_gap", "queue_drop", "store_failure",
        "process_crash", "orphan_span", "export_incomplete",
    ]]
    attribute_registry_version: str
    operation_taxonomy_version: str
    semantic_convention_version: str | None
    hash_key_id: str | None
    hash_algorithm: str | None
    attributes: dict[str, JsonValue]
    error_code: str | None
    span_count: int
    event_count: int
    dropped_record_count: int

class SpanRecord(BaseModel):
    schema_version: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    component: SpanComponent
    kind: Literal["internal", "server", "client", "producer", "consumer"]
    status: Literal["running", "ok", "error", "cancelled", "abandoned"]
    lifecycle_version: int
    last_command_id: str | None
    completion_status: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: float | None
    duration_estimated: bool
    attributes: dict[str, JsonValue]
    error_code: str | None
    exception_type: str | None
    error_message_template: str | None
    error_message_hash: str | None
    dropped_attribute_count: int
    dropped_event_count: int

class TraceEvent(BaseModel):
    schema_version: str
    event_id: str
    trace_id: str
    span_id: str
    producer_sequence: int | None
    stream_sequence: int | None   # 只能由 SQLite single writer 分配
    name: str
    severity: Literal["debug", "info", "warning", "error"]
    occurred_at: datetime
    attributes: dict[str, JsonValue]
    size_bytes: int

class SpanLink(BaseModel):
    schema_version: str
    link_id: str
    trace_id: str
    span_id: str
    linked_trace_id: str
    linked_span_id: str | None
    relation: Literal[
        "queued_from", "resume_of", "retry_of", "reused_from",
        "continued_from", "checkpoint_of", "linked_from_remote",
    ]
    attributes: dict[str, JsonValue]

class TraceArtifactRef(BaseModel):
    schema_version: str
    ref_id: str
    trace_id: str
    span_id: str
    artifact_type: Literal[
        "run", "task", "checkpoint", "manifest", "entity", "chunk",
        "edge", "evidence", "decision", "generation", "report",
    ]
    artifact_id: str
    content_hash: str | None
    repo_id: str | None
    index_version_id: str | None
    role: str

class MetricSnapshot(BaseModel):
    schema_version: str
    snapshot_id: str
    trace_id: str | None
    span_id: str | None
    metric_name: str
    metric_type: Literal["counter", "gauge", "histogram"]
    value: float | None
    count: int | None
    sum: float | None
    bucket_counts: list[int]
    explicit_bounds: list[float]
    attributes: dict[str, JsonValue]
    telemetry_complete: bool
    recorded_at: datetime

class TracePersistenceStatus(BaseModel):
    schema_version: str
    trace_id: str
    status: Literal["queued", "persisting", "persisted", "failed", "dropped"]
    attempt_count: int
    error_code: str | None
    updated_at: datetime

class TraceExportJob(BaseModel):
    schema_version: str
    export_job_id: str
    trace_id: str
    exporter: Literal["otlp_http"]
    status: Literal["queued", "exporting", "exported", "failed", "dropped"]
    attempt_count: int
    next_attempt_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

class TelemetryCommand(BaseModel):
    schema_version: str
    command_id: str
    command_type: Literal[
        "trace_start", "span_start", "span_event", "span_link",
        "artifact_ref", "span_end", "trace_end",
    ]
    trace_id: str
    span_id: str | None
    lifecycle_sequence: int
    occurred_at: datetime
    payload: dict[str, JsonValue]
```

`TelemetryCommand` 是 Internal Recorder 到 Queue/Store 的唯一写入合同。相同 `command_id` 只能应用一次；Batch retry 不得重复 Event、Link 或 Artifact。Span 生命周期固定为 `missing → running → ok|error|cancelled|abandoned`，Trace 生命周期固定为 `missing → running → completed|partial|failed|cancelled|abandoned`。禁止 terminal 回到 running，也禁止以另一个 terminal 覆盖已完成终态。

`span_start` 使用幂等 INSERT；`span_end` 使用带 lifecycle version/terminal guard 的条件 UPDATE。若 end 早于 start，Writer 将 end 放入有界 pending-terminal 表，等待同 batch/恢复窗口内的 start；窗口结束仍缺 start 时创建带 `missing_span_start|orphan_span` 的终态占位记录，不能伪造精确 start。重复相同 terminal command 幂等忽略；冲突 terminal 拒绝并增加 integrity counter。

业务线程不更新 Trace 的 span/event counts。single writer 在事务内最终化或查询时计算计数，避免并发 lost update。Span Handle 在进程内用 `time.monotonic_ns()`/`perf_counter_ns()` 计算精确 duration；`started_at/ended_at` 只用 UTC wall clock 展示与过滤。崩溃恢复的 abandoned duration 可以用 wall clock 估算，但必须 `duration_estimated=true`。

完整性规则：正常 root 完结且无 flag 才为 `complete`；任何 drop/missing/crash/store/export gap 为 `partial`；无法判断为 `unknown`。Store 正常且 Queue 未溢出时，目标为 100% metadata；故障时是明确标记完整性的 best-effort，而不是绝对保证。

默认硬限制：每 Span 最多 64 个属性；key 128 字符；普通字符串 1,024 字节；Span attributes 合计 16 KiB；Event 8 KiB；每 Span 32 Links；每 Trace 200 ArtifactRef。超限字段先按 Registry拒绝或安全截断并记录 dropped count；Secret 命中直接拒绝，绝不先截断再保存。

## 6. Attribute Registry 与 Span 分类

### 6.1 内部属性注册表

使用版本化 `cra.*` 注册表，只有注册过的 key/type/cardinality/content policy 可写入。每个 Attribute 定义至少包含：

```text
key
value_type
cardinality
content_policy
metric_label_allowed
introduced_in
deprecated_in
removed_in
replacement_key
value_schema_version
```

API 读取旧 Trace 时必须按 Trace 自身的 Registry Version 解释，不能以新版含义解释旧 Key。Deprecated Key 仍可读取，但新写入被拒绝或产生受限 warning；Removed Key 不得静默映射。Trace Compare 必须输出：

```text
comparison_compatibility = compatible | partially_compatible | incompatible
```

注册表内容包括：

- Identity：`cra.trace.type`、`cra.component`、`cra.operation`、`cra.request.id`、`cra.run.id`、`cra.task.id`。
- Version：`cra.repo.id`、`cra.index.version_id`、`cra.schema.version`、`cra.generation.id`、`cra.profile.hash`。
- Outcome：`cra.status`、`cra.error.code`、`cra.retry.count`、`cra.fallback.reason`、`cra.cancel.requested`。
- Retrieval：channel、hit/candidate/context counts、hop、reranker、empty/fallback。
- Agent：route、plan steps、tool calls/reuse、replan、evidence count、budget usage、stop reason。
- Provider：provider/model/revision/prompt version、tokens、cache、attempt、timeout、estimated cost/profile。
- Alignment：profile/candidate/selection counts、decision status、verifier fallback、review authority。

run/repo/entity 等高基数值可用于 Trace 查询，但不得作为在线 Metrics label。属性值必须先经 Registry 验型和 Redactor。

### 6.2 Root Policy、Child Span 与 Span 名称

唯一 Root 规则是：**只有不存在有效本地父上下文时，业务操作才能创建 Root Trace。** 统一入口设计为：

```python
def start_span_or_root(
    *,
    operation: str,
    trace_type: TraceType,
    parent_context: TraceContext | None,
) -> SpanHandle:
    ...
```

固定策略：

```text
同步 API 请求
→ api_request Root

API enqueue 后台 Analysis / Research Agent / Alignment
→ 新对应业务 Root
→ queued_from Link 关联 API Trace

独立 Index Build 且无本地 Parent
→ indexing Root

独立 Retrieval 且无本地 Parent
→ retrieval Root
```

嵌套调用必须继承本地 parent 并创建 Child Span：

```text
agent.run
└── retrieval.search

analysis.run
└── provider.generate

alignment.run
└── retrieval.search
```

不得为 Agent、Alignment、Analysis 或 API 内的 Retrieval/Provider/Tool 再创建第二个 Root Trace。

这里的“Root”指本地业务执行入口。`REMOTE_PARENT_MODE=continue` 时 API Server Span 在分布式 W3C Trace 中仍有 remote parent，因此不是全局 root；`link|ignore` 时才创建新的本地 trace_id。无论哪种模式，后续本地嵌套调用都只创建 Child Span。

| Trace type | Root | 主要 Child Span | 内容策略 | 预算 |
| -- | -- | -- | -- | -- |
| api_request | `api.request` | access policy、service enqueue、error mapping | route template，禁 body/header | 无本地 parent 的同步请求 1 root |
| analysis | `analysis.run` | `analysis.node`、provider、artifact | node/status/count，不存 State | 每 node 1 Span |
| indexing | `indexing.build` | fingerprint/entity/edge/evidence/chunk/persist/activate | ID/hash/count | 每阶段 1 Span，DB batch 不逐 row |
| retrieval | 独立时 `retrieval.search` Root；嵌套时同名 Child | sparse/dense/preliminary_rrf/graph/final_rrf/rerank/context/citation | query type/count/hash，禁 query/text | 每 channel 1 Span，不重复 Root |
| research_agent | `agent.run` | route/plan/bind/tool/assess/replan/checkpoint/answer/finalize | ID/count/budget，禁 State/Prompt | 每 node attempt 1 Span |
| alignment | `alignment.run` | profile/recall/feature/score/calibrate/verify/persist/activate/review | count/type/hash，禁论文/源码 | 每 stage 1 Span |

Component 还包括：`provider.generate`、`tool.execute`、`database.transaction`、`checkpoint.read|write`、`cache.get|set`。错误用标准 Span status + `exception` Event，Event 只含异常类、稳定 error code、脱敏消息和 retryable，不存 stack locals、SQL 参数或 payload。

## 7. Trace Context 传播

```text
FastAPI
→ Service
→ LangGraph config
→ Node
→ ToolExecutionContext
→ Retrieval
→ Provider
→ Store/Checkpoint/Cache
→ Alignment
```

### 7.1 W3C Remote Parent

新增配置：

```text
OBSERVABILITY_REMOTE_PARENT_MODE=link
允许值：continue | link | ignore
```

- `continue`：合法远端 Context 作为 remote parent，本地 Server Span 继续远端 trace_id。
- `link`（首版默认）：创建新的本地 Trace ID，通过 `linked_from_remote` SpanLink 关联合法远端 Context。
- `ignore`：忽略远端 Context并创建全新本地 Trace。

处理顺序固定为：先严格验证 `traceparent`/`tracestate` 长度、hex、全零 ID、flags 和字符集，再应用 mode。非法 Context 被忽略并产生不含原始 Header 的安全 Event；完整 `traceparent`/`tracestate` 不写 Attribute、日志或错误响应。

**Trace context is correlation data, never authorization data.** 远端 trace_id、tracestate、baggage 或 caller scope hash 均不能改变 Access Policy、repo membership、Run ownership 或 index version。`continue` 只适用于已明确受信的部署边界，也必须独立授权。

### 7.2 本地传播与异步边界

1. `request_id` 是服务端 HTTP 关联 ID；`trace_id` 是调用树 ID；`run_id/task_id` 是业务身份。三者不得互换。
2. 同步 Service 使用 `contextvars` 传播不可变 `TraceContext`；显式参数用于线程、Coordinator 和 Tool 边界。
3. LangGraph config 只放可序列化的小型 trace/span IDs、recording decision 和 registry version，不放 Recorder、Provider、DB 或完整上下文对象。
4. 任何 Service 先调用 `start_span_or_root`：有有效本地 parent 就创建 Child，没有 parent 才按第 6.2 节创建 Root。
5. 202 API root 在 enqueue 后结束；后台 Analysis/Agent/Alignment 创建独立 Trace，用 `queued_from` Link 连接 API Trace，避免跨生命周期伪父子。
6. Resume 新建执行 Trace并 `resume_of` Link 上一次 Trace；Run ID 保持业务语义。Retry Run 使用 `retry_of`；Tool Observation reuse 使用 `reused_from` 连接原 Tool Span。
7. Checkpoint 仅保存必要 trace correlation metadata；恢复时若原 Trace 不存在仍可运行，新 Trace 记录 `orphan_span`/link warning。
8. 所有 Child Context 继承并二次验证 repo/index version；上下文传播不得允许跨版本访问。

## 8. OpenTelemetry 设计

本轮调查使用 OpenTelemetry 官方 Python、Exporter、Propagation、Trace API 和 Semantic Conventions 文档作为实施依据：[Python 状态](https://opentelemetry.io/docs/languages/python/)、[Exporter](https://opentelemetry.io/docs/languages/python/exporters/)、[Propagation](https://opentelemetry.io/docs/languages/python/propagation/)、[Trace API/Links](https://opentelemetry.io/docs/specs/otel/trace/api/)、[Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)。截至 2026-07-18，PyPI 上 API/SDK 为 1.44.0，FastAPI instrumentation 为 0.65b0；后者仍是 beta，因此正式依赖必须经过与 FastAPI/httpx/LangGraph 的 compatibility spike 后锁定安全范围，不能只按“最新版”安装。

### 8.1 唯一单向数据流

固定且唯一的主数据流是：

```text
业务代码
→ Internal Recorder
    ├── Local SQLite Persistence Sink
    └── OTel Adapter
          └── optional OTLP HTTP Exporter
```

- Internal Recorder 是项目内唯一 Trace 入口，业务代码不得直接创建 OTel Span。
- SQLite Store 直接消费 `TelemetryCommand`；它是本地 Persistence Sink，不是 OTel Exporter。
- OTel Adapter 只是 Internal Record 到 OTel SDK 的单向下游映射；OTel 不得再导出回 Internal SQLite。
- 禁止 `Internal → OTel → SQLite → Internal` 闭环，也禁止同一 operation 被手动与自动 instrumentation 各创建一个 Span。
- Noop/InMemory 是 Internal Recorder/Sink 测试实现；OTLP HTTP 才是外部 Exporter。

新增配置：

```text
OBSERVABILITY_HTTP_INSTRUMENTATION=manual
允许值：manual | otel_auto
```

首版使用项目手动 FastAPI Middleware，OTel FastAPI/database/http-client/Provider 自动插桩默认关闭。未来启用 `otel_auto` 时必须关闭对应手动 Span；配置校验拒绝同时启用，不能依靠运行时去重补救。

### 8.2 Adapter、Resource 与关闭

- v1.8-a/b/c 的 Internal Recorder 不依赖 OTel。
- v1.8-d 增加 OTel API/SDK Adapter，将已验证、已脱敏的 Internal metadata 映射到 OTel，不让 OTel 对象进入业务 State。
- 只采用稳定 HTTP 属性；GenAI conventions 变化时继续使用版本化 `cra.*`，并记录 adopted semantic convention version。禁止使用已废弃属性。
- Resource 只含 `service.name=code-research-agent`、service version、environment、instance hash、telemetry SDK/version；默认不暴露用户名、绝对路径或 hostname。
- lifespan 初始化 Adapter/Processor/OTLP Exporter，关闭时有界 `force_flush` 后 shutdown。Exporter failure 只增加 telemetry failure/drop metrics，不影响请求。
- OTLP endpoint/header 由 Secret-aware config 管理；Trace DB/API 永不返回 Authorization header。
- OTel export 在 `suppress_observability()` 中运行，避免导出 HTTP 被再次插桩。

## 9. 隐私、Redaction 与授权

默认：

```text
OBSERVABILITY_DETAIL_LEVEL=metadata
OBSERVABILITY_OTLP_ENABLED=false
OBSERVABILITY_API_ENABLED=false
OBSERVABILITY_HMAC_KEY_ID=<secret-config-key-id>
```

v1.8 第一版不实现 Content 模式。允许的记录级别只有 `none|metadata|diagnostic_metadata`；Query 原文、Prompt、Model Response、完整代码、论文正文、Secret、Authorization、Cookie、connection string、原始 Checkpoint、上传文件内容、完整 State 和原始异常字符串均禁止进入 Trace DB。

`AttributeRegistry` 先做 key allowlist/type/size，再由 `Redactor` 检测 secret pattern、敏感 header/path/URL/query 参数。标识符按用途保存稳定 ID或 HMAC hash；不得用无盐 SHA 暴露低熵 secret。错误消息只保留注册模板和 error code。

### 9.1 错误与 HMAC

- `SpanRecord` 不保存任意 `error_message`。Error Event 只保存稳定 error code、Registry 中登记的 `error_message_template`、安全 `exception_type` 与可选 `error_message_hash`。
- 不保存原始异常字符串、Stack trace、stack locals、SQL 参数、Provider response、Query、用户路径或正文。
- HMAC Key 从 Secret-aware 配置读取，Key 本身不进入 Trace DB/API/日志；Trace 只保存 `hash_key_id + hash_algorithm`。
- Key 不可用时，要求 HMAC 的低熵字段 fail closed 或完全不记录，不能回退无盐 hash。
- 轮换后新 Trace 使用新 `hash_key_id`；旧 Key 只按 retention/审计窗口加密保留，窗口结束安全销毁。历史 hash 不承诺跨 Key 可关联。

### 9.2 Artifact 与 Retention

需要查看业务原始数据时只保存 `TraceArtifactRef`，由原事实库、Run Store、Checkpoint 或报告权限系统另行读取；Trace API/UI 不内联 Artifact 内容。Content Capture 可作为未来独立安全评审项，但不属于 v1.8。

默认 metadata/diagnostic metadata retention 为 14 天，实际值在性能与合规验收时冻结。每个 Attribute/Event/Trace 有 byte cap；超限与拒绝只产生不含原内容的 counter。API 还必须执行统一 Access Policy 和响应 Redaction。

## 10. Trace Store、Queue 与 Retention

使用独立 `data/observability.sqlite3`，不修改事实库、Research/Alignment Store 或 Checkpoint DB。表至少为：

- `traces(trace_id PK, root_span_id, type, caller/repo/version/run/task, lifecycle/status, time/duration, recording/completeness/integrity, registry/semconv version, error, counts)`。
- `spans((trace_id,span_id) PK, parent, component/name/kind/lifecycle/status/time/duration/estimated, bounded attributes/safe error/drop counts)`。
- `telemetry_commands(command_id PK, trace/span, type, lifecycle_sequence, occurred_at, applied_at, result)`，用于幂等 batch retry 与审计。
- `pending_span_terminals(command_id PK, trace/span, lifecycle_sequence, payload, expires_at)`，有界处理 end-before-start。
- `span_events((trace_id,event_id) PK, span_id, producer_sequence, stream_sequence, time/name/severity/attributes/size)`，并唯一约束 `(trace_id,stream_sequence)`。
- `trace_stream_sequences(trace_id PK, next_sequence, updated_at)`，由 single writer 分配 SSE 游标。
- `span_links(link_id PK, source trace/span, linked trace/span, relation, attributes)`。
- `trace_artifact_refs(ref_id PK, trace/span, artifact type/id/hash/role)`。
- `trace_metric_snapshots(snapshot_id PK, trace/span, metric/value/buckets/time/labels)`。
- `trace_persistence_status(trace_id PK, status/attempt/error/updated_at)`，描述本地 command 持久化。
- `trace_export_jobs(export_job_id PK, trace, exporter=otlp_http, status/attempt/time/error)`，只描述外部导出。

为 time/status/type/component/operation/repo/index/run/error/duration 建索引；外键删除只级联同一 Trace telemetry。SQLite 使用 WAL、foreign keys、bounded busy timeout、`synchronous=NORMAL`、单 writer batch 和短事务。

### 10.1 Command、Single Writer 与完整性

默认队列/批参数为待验收初值：4,096 commands、batch 128、250ms flush、shutdown flush 3s。业务线程只做校验、Redact 和非阻塞 enqueue。single writer按 `command_id` 幂等应用，验证 lifecycle sequence，拒绝 terminal逆转/冲突，并在同一事务内写 Event 与分配 `stream_sequence`。

Event Producer 只能设置局部 `producer_sequence`；全 Trace 唯一递增的 `stream_sequence` 由 Store Writer 读取/更新 `trace_stream_sequences` 后分配。live buffer 只发送“某 Trace 有新 sequence”的唤醒通知，不保存事实 Event。

队列满时依次丢 diagnostic Event、普通 Event、非终态 Span update；为 root/error/terminal 留 reserved capacity，但仍不阻塞业务。任何 drop 都把关联 Trace 标为 `partial + queue_drop`；无法定位具体 Trace 时增加全局 telemetry incomplete counter。Store failure、进程 crash、missing start/end、sequence gap、orphan 和 export incomplete 使用对应 integrity flag。Metrics 聚合携带 `telemetry_complete=false`，不得把 partial/unknown Trace 当精确业务事实。

Batch 写失败有限 retry；持续失败熔断至 Noop/InMemory counters。Store 不可用不触发业务事务 rollback。启动时把超过阈值仍 running 的 Span 标记 abandoned，并以 Event 说明检测时间，不猜测业务结果。

Retention 由独立 job 按 ended_at、recording mode、persistence/export status 和 legal hold policy 删除，使用小批事务；不删除业务 Artifact。Export job 不得永久阻塞 retention，超期 failed job按策略转 dropped、添加 `export_incomplete` 并保留聚合计数。Cursor 已落入 retention gap 时返回 `trace_cursor_expired`。

### 10.2 自我插桩抑制

新增：

```python
@contextmanager
def suppress_observability():
    ...
```

底层使用 `contextvars` 设置 `observability_suppressed=true`。Observability SQLite读写、migration、Queue batch flush、Retention、OTLP export、telemetry health持久化、Recorder/Redactor错误处理，以及 Trace API 对 Observability DB 的底层查询，全部必须在 suppression 中执行。HTTP Trace API Root Span可以存在，但其 Store read不再产生 database Child Span，防止 `Trace Store → database span → Trace Store` 递归。

被 suppression 的代码路径仍允许更新最小进程内 drop/failure counter，但不得递归调用 Recorder。Database/HTTP自动插桩适配器必须首先检查 suppression flag。

## 11. 采样

使用 `RecordingDecision` 分离三种语义：

- `record_metadata`：是否持久化本地基础 metadata。启用 Observability 时首版目标为全部记录，但受 Queue/Store故障影响时必须标记完整性。
- `record_diagnostics`：是否额外保存增强诊断 metadata，例如更细 Timing、有限 reason code；仍禁止业务正文。
- `export_otlp`：是否进入外部 OTLP Head Sampling，与本地记录独立。

`trace_flags` 只表示 W3C/OTel传播 Flag，不能代表本地 SQLite 记录或 diagnostic decision。`TraceRecord.recording_mode`、`diagnostic_sampled`、`otlp_sampled` 分别持久化实际决策。

Root 开始时做一次 Head Decision并向 Child传播；Child不能自行提升模式。Root开始时不知道最终是否 slow/error，因此结束时只能保证保留已经采集的本地 metadata并添加 terminal reason，不能恢复此前未采集的 Child诊断信息，也不能宣称得到完整 Tail-sampled OTLP Trace。真正 Tail Sampling需要外部 Collector或结束后完整 Trace导出，不属于首版。

第一版推荐：本地 metadata启用时全部记录、diagnostic metadata确定性采样、OTLP独立 Head Sampling、业务内容永不记录。Sampler 只使用低敏 metadata：trace type、route template、稳定 hash和受限配置；不读 query/prompt。测试使用固定 seed/hash的 `DeterministicSampler`。所有未记录、drop和export skip均有 reason code/metrics，未采样不等同于失败。

## 12. 实时事件与 SSE

只把受控 lifecycle 转为 Event：API enqueue、Analysis task/node、Agent/Alignment stage、Tool start/end、checkpoint metadata、cancel/terminal/error。禁止把 LangGraph `debug` 或完整 `values` State直接返回前端。

设计接口：

```text
GET /observability/traces/{trace_id}/events/stream
Accept: text/event-stream
```

- Producer只提交局部 `producer_sequence`；SQLite single writer在 Event落库的同一短事务分配 Trace内唯一递增的 `stream_sequence`。`event_id`用于对象身份，不作为续传顺序。
- SSE 固定使用 `Last-Event-ID = stream_sequence`。服务端先读取 `stream_sequence > cursor` 的持久 Event，再订阅 live唤醒并重新查询 Store；不得直接把进程内对象当事实输出。
- 持久读取到 live订阅之间使用“订阅后再次读当前 high-water mark”的握手避免竞态；客户端按 `(trace_id,stream_sequence)` 去重，确保重连无 gap/duplicate。
- 每连接有 buffer、心跳和最大 backlog；慢客户端断开并可重连，绝不反压 Agent/Alignment Run。
- terminal Event 写入并 drain 后关闭；网络断开不取消业务 Run。
- SSE 调用统一 `ObservabilityAccessPolicy`，权限与 Trace Detail完全一致；过期 cursor返回 `trace_cursor_expired`，无权与不存在统一404。
- 多进程第一版以 SQLite polling/sequence 为一致来源，不依赖进程内队列作为唯一事实。
- Queue drop或检测到 sequence gap时 Trace立即标记 partial；SSE发送不含业务内容的 `telemetry.integrity_changed` Event。SSE终端关闭只能表示当前持久流已结束，不代表 Trace一定 complete。

## 13. Metrics

### 13.1 实时低基数 Metrics

- 系统：request count/error/latency、coordinator queue depth、telemetry queue depth/drop、export/store failure。
- Retrieval：channel count/latency、empty/fallback、reranker enabled/fallback。
- Agent：route、tool call/reuse/failure、replan、partial、budget exhaustion、recovery、cancel。
- Provider：request/timeout/fallback/cache hit、input/output token、known estimated cost。
- Alignment：candidate count bucket、accepted/abstained/needs-review、verifier fallback、review action。

Labels 只用 bounded enum/status/component/model family；不得使用 run/repo/query/entity/error message 等高基数值。

### 13.2 Trace 离线聚合

按 repo/run、P50/P95、Evidence flow、具体 operation、retry/link、long-tail 和大 Trace 从 SQLite离线聚合。实时 counter 和离线聚合必须标明窗口与数据完整度；任何来源 Trace 为 partial/unknown 时输出 `telemetry_complete=false`、integrity flag counts 和 excluded/included policy，不得把结果表示为精确全量业务指标。

Provider cost 只有在 `pricing_profile_id + currency + effective_at` 固定且 token 已知时计算；否则返回 null。v1.8 不声称精确账单。

## 14. Trace API

新路由始终注册。Recorder 与读取面分别控制：`OBSERVABILITY_ENABLED=false` 使用 Noop；`OBSERVABILITY_API_ENABLED=false`（首版默认）时所有读取路由稳定返回 HTTP 503 `observability_api_disabled`：

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

List 支持 cursor pagination、UTC start/end、status/type/component/operation、repo/index、run/task/request、error code 和 duration range；默认 50、最大 200。必须限制时间窗口、Span/Event page、聚合 points、单响应 2 MiB，禁止无限导出。

Span ID仅在 Trace内唯一；所有 Span Detail、Link、ArtifactRef、Store查询和权限校验均使用 `(trace_id,span_id)`，不得假设 span_id全局唯一。

### 14.1 统一 Access Policy

```python
class ObservabilityAccessPolicy(Protocol):
    def can_list_traces(
        self, caller: CallerIdentity, filters: TraceFilter,
    ) -> bool: ...

    def can_read_trace(
        self, caller: CallerIdentity, trace: TraceRecord,
    ) -> bool: ...

    def can_read_diagnostic_metadata(
        self, caller: CallerIdentity, trace: TraceRecord,
    ) -> bool: ...
```

读取面启用后至少要求 local admin、authenticated caller或显式 repository membership。在真实认证系统尚未建立时，默认只允许由受信本地配置确认的 local admin；任意 `X-Caller-Scope` 等自报 Header及 `caller_scope_hash` 只能关联，不能授予权限。

Trace List、Detail、Span、Event、SSE、Metrics和Compare必须调用同一 Policy。无权与不存在统一返回404；Policy failure不泄露 Trace存在性。Diagnostic metadata需要独立权限，普通 metadata权限不能自动升级。

Detail 返回脱敏 attributes、完整性、Links和ArtifactRef，不内联 Artifact 内容。稳定错误码：`observability_disabled`、`observability_api_disabled`、`trace_not_found`、`span_not_found`、`invalid_trace_filter`、`trace_store_unavailable`、`trace_cursor_expired`、`trace_response_too_large`、`metrics_range_too_large`、`event_stream_limit`；Access denied 对外映射为统一404。

## 15. Trace Explorer

最小前端新增独立路由与 feature：

- Trace List：时间、type、status、duration、run/repo、error/filter。
- Span Tree 与 Waterfall：normal parent/child、queued/retry/resume/reused Link、并行、orphan、missing start/end、aggregated children、critical path、abandoned。
- Span Detail：注册属性、Events、错误、Token/known cost、fallback、Artifact/Evidence refs。
- Live Run：SSE lifecycle、自动重连、terminal close。
- 完整性：明确显示 `complete`、`partial telemetry`、`unknown completeness`、abandoned、sequence gap、dropped records、store failure和orphan span；不完整 Trace不得渲染成无缺口调用链。
- Trace Compare：只比较 metadata、operation duration/status/count，不执行历史 Run。比较前检查 Attribute Registry Version、Graph Version、Operation Taxonomy Version、Model/Scorer Profile、Recording/Sampling和Completeness；输出 compatibility。不兼容时只能并排展示，不能声明性能回归。

禁止显示 Secret、Prompt、完整代码、论文正文、原始 Checkpoint、完整 State、任意原始 error message 或无限响应。所有页面使用同一 `ObservabilityAccessPolicy`；后端默认最多返回 2,000 spans，UI 对 1,000+ Span使用虚拟列表/懒加载，Waterfall按层级分页或聚合，Event 每页最多 500。

## 16. Replay 边界

v1.8 只支持 timeline reconstruction、Trace compare、Checkpoint Artifact link 和 `ReplayManifest` 设计。Manifest 仅描述原 run/repo/version/config/model/prompt/tool/generation hashes、所需 Artifact availability 和 `replay_ready|not_ready` 原因，不含 Secret/Prompt/State，也不触发执行。

真正重新执行、模型对比、自动评测和 Bad Case 回归留到 v1.9，必须另行授权和预算。

## 17. 性能预算

开工时用当前 v1.7 Commit在同一机器冻结基线。建议初始目标：

- Noop：Recorder 调用 P95 <0.2ms，端到端 P95 增量 <0.5%。
- Metadata：业务端 enqueue P95 <1ms；各主流程 P95 业务延迟增量 <5%。
- Trace 写失败不得增加业务失败率或改变结果。
- 正常 Span 的 `duration_ms` 必须由 monotonic/perf-counter clock计算；wall-clock跳变测试不能产生负 duration。Crash后 abandoned估算必须显式标记。
- Metadata Span 序列化 <=4 KiB，Event <=8 KiB；默认 Trace <=2,000 spans、10,000 events、1 MiB metadata，超限聚合/drop并告警。
- Queue 4,096、batch 128、flush 250ms、shutdown 3s 为初值；必须按压测冻结。
- SQLite 单 writer 在参考机器持续 >=1,000 records/s，且业务 Store busy/error率无显著增加。
- API 单响应 <=2 MiB；timeseries <=2,000 points；前端最大 Span 2,000并虚拟化。

若本地基线证明目标不现实，必须在 v1.8-a 记录机器、数据、冷/热状态后显式调整，不能静默放宽。

## 18. 推荐目录与文件边界

### 18.1 新增

```text
backend/app/observability/
  __init__.py
  schemas.py
  commands.py
  attributes.py
  redaction.py
  sampling.py
  recorder.py
  context.py
  suppression.py
  access_policy.py
  metrics.py
  otel_adapter.py
  api.py
backend/app/persistence/
  observability_store.py
  observability_migrations/001_observability.sql
backend/app/services/
  observability_runtime.py
frontend/src/features/observability/
tests/observability/
scripts/benchmark_observability.py
docs/observability_v1.8.0.md
```

### 18.2 受控修改

- `backend/app/main.py`：lifespan、middleware、router；业务路由语义不变。
- Analysis graph/progress、Index Service、Retrieval Service、Research/Alignment Graph/Coordinator、Provider Runtime、Tool Registry、Store adapter：只注入 Recorder/Context，不改业务算法或事务。
- `pyproject.toml`：v1.8-d 才增加经过 spike 的可选 `observability` extra。
- frontend router/API client：只增加 Explorer，不改旧页面。

禁止修改 v1.4 事实 Schema/ID、v1.5 排序、v1.6 Agent决策/恢复语义、v1.7 Alignment评分/Deployment/Review、Provider payload/consent 语义。

## 19. 分阶段实施

### v1.8.0-a：Trace Contract、Root Policy、Command、隐私、采样、权限与 Mock

- 输入：本计划、v1.7 ID/error/privacy事实、OTel compatibility调查。
- 输出：Root/Child Policy、Remote Parent mode、核心 Schema、`TelemetryCommand`、生命周期/完整性、Attribute Registry lifecycle、Redactor/HMAC合同、`RecordingDecision`、`ObservabilityAccessPolicy`、Noop/InMemory Recorder、性能基线。
- 修改文件：新增 observability schemas/commands/attributes/redaction/sampling/context/access_policy/recorder与单元测试；不插桩业务。
- 新增依赖：无。
- 测试：严格 Schema、start_span_or_root、remote mode、生命周期逆转、Registry兼容、raw error/content拒绝、HMAC key unavailable、deterministic decisions、Access Policy和Noop。
- 验收：嵌套操作不创建额外 Root；默认 remote link；无 Content模式；非法对象与低熵未HMAC字段fail closed；Noop达到冻结预算。
- 回滚点：不注册 runtime，所有业务继续原样运行。

### v1.8.0-b：Core Recorder、Bounded Queue、Single Writer、SQLite、Sequence、Retention 与 Suppression

- 输入：v1.8-a合同和基准。
- 输出：幂等 command queue/batch、独立 migration/Store、pending terminal、single-writer stream sequence、persistence状态、abandoned recovery、integrity flags、retention、shutdown flush、suppression和failure counters。
- 修改文件：新增 observability runtime/suppression/store/migration、store/queue/SSE-sequence测试。
- 新增依赖：无，使用标准库 sqlite3/asyncio。
- 测试：duplicate/out-of-order command、terminal conflict、WAL/busy、batch retry、concurrent sequence、overflow/integrity、Store unavailable、abandoned、retention、suppression、flush/migration。
- 验收：Command最多应用一次；sequence Trace内递增；Store自身不递归插桩；故障不影响模拟业务；所有不完整原因可查询。
- 回滚点：切换 Noop并停止 writer；Trace DB为可删除派生数据。

### v1.8.0-c1：API、Provider、Cache 与 Retrieval 插桩

- 输入：Core Recorder、Root Policy和现有同步 Retrieval链路。
- 输出：`API Root → Retrieval Child/Root policy → Provider/Cache Child → Response` 垂直链路，手动HTTP instrumentation和受限错误映射。
- 修改文件：main/middleware、Retrieval Service、Provider Runtime、Cache adapter及专项测试；不改排序/Provider选择。
- 新增依赖：无。
- 测试：standalone/嵌套 Retrieval、manual server span唯一性、remote parent modes、Sparse/Dense/RRF/Graph/Reranker spans、token/cache/timeout、monotonic duration。
- 验收：Recorder On/Off业务响应与排序等价；隐私扫描通过；P95增量达标；既有API/Retrieval/Provider回归通过。
- 回滚点：Noop Recorder并关闭 middleware执行；业务链路保持原样。

### v1.8.0-c2：Research Agent、Tool、Checkpoint 与 Coordinator 插桩

- 输入：c1传播合同、ResearchRunStore/Checkpointer/Coordinator实际边界。
- 输出：queued_from、route、plan、tool、reuse、replan、resume、retry、cancel、partial和checkpoint Artifact spans/links。
- 修改文件：Research Coordinator/Graph runtime wrapper、Tool Registry/Executor、Checkpoint adapter及测试；不改Graph条件或State语义。
- 新增依赖：无。
- 测试：后台Agent Link、Retrieval Child不建Root、Tool reuse Link、Replan、resume/retry、cancel/partial、checkpoint suppression/artifact、orphan恢复。
- 验收：Recorder On/Off Run终态、预算、工具次序、恢复结果等价；隐私/性能/Agent全回归通过。
- 回滚点：关闭Agent instrumentation，RunStore/Checkpoint不依赖Trace。

### v1.8.0-c3：Analysis、Structured Index、Alignment 与业务 DB Adapter 插桩

- 输入：c1/c2稳定合同、Analysis/Index/Alignment阶段边界。
- 输出：后台Analysis Link/node、Index build/activate、Alignment stages/verifier/review和业务DB spans；Observability DB继续suppressed。
- 修改文件：Analysis graph/progress、Index Service/Store adapter、Alignment Service/Coordinator/Store adapter及测试；不改业务事务。
- 新增依赖：无。
- 测试：background Analysis Link、Provider Child、Index failure isolation、Alignment Retrieval Child、Lease/cancel/retry、business DB span、Observability DB无span。
- 验收：Recorder On/Off产物、active version、Alignment decision/Deployment与状态机等价；隐私/性能/旧功能回归通过。
- 回滚点：关闭对应component instrumentation；Analysis/Index/Alignment独立运行。

每个 c 子阶段必须独立执行：Recorder On/Off业务输出等价、隐私扫描、性能测试和全部受影响旧功能回归；不得等到 c3 才集中发现语义回退。

### v1.8.0-d：OTel 单向 Adapter、Metrics 与可选 OTLP

- 输入：Internal Recorder、已锁定 compatibility spike结果。
- 输出：单向 OTel Adapter、Resource、Processor、可选 OTLP HTTP和低基数Metrics；SQLite继续为Internal Persistence Sink。
- 修改文件：新增 `otel_adapter.py`/metrics/config/tests；可选更新pyproject extra/lock/docs。
- 新增依赖：预计同兼容族OTel API/SDK/OTLP；FastAPI auto instrumentation仅在选择`otel_auto`时可选，精确版本由spike冻结。
- 测试：单向mapping、manual/auto互斥、semconv、diagnostic/OTLP sampling分离、suppressed export、failure/retry/flush、无网络单测。
- 验收：Internal Recorder唯一入口；不存在双Span/闭环；OTLP默认关；Exporter失败不影响业务。
- 回滚点：关闭 OTel/OTLP，继续 Internal SQLite或Noop。

### v1.8.0-e：Trace API、SSE、Access Policy 与 Query

- 输入：Trace Store、persisted stream sequence、统一Access Policy。
- 输出：八个Trace/Metrics API、复合Span Detail、cursor filter、response redaction、SSE reconnect/backpressure/terminal close。
- 修改文件：新增observability API并注册main；API/SSE/权限测试。
- 新增依赖：无，复用FastAPI `StreamingResponse`。
- 测试：API默认503、local admin/repository membership、无权统一404、trace+span key、分页/范围/大小、Last-Event-ID、持久sequence、慢连接、Store unavailable。
- 验收：SSE与Detail共用Policy；无gap/duplicate；SSE失败不影响Run；所有响应受限/脱敏并显示完整性。
- 回滚点：关闭 API flag；Recorder/业务可继续或单独关闭。

### v1.8.0-f：Trace Explorer、性能、故障注入、文档与完整回归

- 输入：Trace API/SSE与冻结设计。
- 输出：List/Tree/Waterfall/Detail/Events/Live/Compare、完整性与兼容性UI、性能/故障注入报告、retention/runbook、v1.8验收文档。
- 修改文件：新增前端observability feature、路由/API client、性能脚本和文档。
- 新增依赖：优先无；如需timeline库须独立审查bundle/license，默认自实现虚拟化视图。
- 测试：large/incomplete/orphan trace、Compare compatibility、SSE reconnect、Redaction/Access UI、Noop/Queue/Store/OTLP failure、全后端/前端/build/validate。
- 验收：Noop/metadata P95达到冻结目标；Explorer不掩盖缺口；旧能力全回归；`ALIGNMENT_BENCHMARK_PENDING`仍被如实报告。
- 回滚点：隐藏 Explorer并关闭API/Recorder；不删除业务数据。

## 20. 测试计划

| 类别 | 必测用例 |
| -- | -- |
| Span/Context | root/child、nested、跨线程/async、remote continue/link/ignore、invalid traceparent、repo/version继承、context不授权 |
| Lifecycle | duplicate/out-of-order command、terminal conflict、crash/abandoned、monotonic duration |
| Link | API enqueue、resume、retry、tool reuse、checkpoint artifact link |
| Analysis/Index | node start/end/error、progress不含 State、activation failure |
| Retrieval | Sparse/Dense/Preliminary RRF/Graph/Final RRF/Reranker/Context child spans、fallback/empty |
| Agent | route、tool、replan、evidence、budget、partial、cancel、resume/recovery |
| Alignment | Profile/Candidate/Feature/Score/Verifier/activate/review、Lease/cancel/fallback |
| Provider/Cache | token、cache hit/miss、fallback、timeout、consent、未知 cost为 null |
| Error | typed error、exception redaction、abandoned span、business/trace状态不一致 |
| Privacy | attribute lifecycle、secret/raw error/content rejection、HMAC key rotation/unavailable、ArtifactRef不内联、oversize |
| Sampling | local metadata、diagnostic与OTLP独立decision、Head限制、deterministic sampler、drop metrics |
| Queue/Store | command幂等、stream sequence、overflow/integrity、batch retry、WAL busy、Store unavailable、shutdown flush、retention、suppression |
| API/SSE | API默认关闭、统一Access Policy、复合Span key、pagination/range/size、SSE persisted sequence/reconnect/backpressure/terminal |
| Performance | Noop、metadata P50/P95、write throughput、大 Trace API/UI |
| Offline | 所有自动测试使用 InMemory/Noop，OTLP无网络，不下载组件 |

另外必须验证：Recorder 抛异常时 Analysis/Index/Retrieval/Agent/Alignment/Provider 的返回、DB状态和排序与 Noop完全一致；现有全部测试、前端 build和 `scripts/validate.sh` 通过。

### 20.1 必须具名的回归用例

Root、Context 与远端传播：

- `test_retrieval_inside_agent_does_not_create_second_root`
- `test_retrieval_inside_alignment_is_child_span`
- `test_standalone_retrieval_creates_root`
- `test_background_agent_links_to_enqueue_api`
- `test_background_analysis_links_to_enqueue_api`
- `test_remote_parent_link_mode_creates_local_trace`
- `test_remote_parent_continue_mode_uses_remote_trace`
- `test_invalid_traceparent_is_ignored_safely`
- `test_remote_context_never_changes_access_control`

Command、生命周期与 Timing：

- `test_duplicate_span_start_is_idempotent`
- `test_duplicate_span_end_is_idempotent`
- `test_conflicting_terminal_span_end_is_rejected`
- `test_span_end_before_start_is_handled_deterministically`
- `test_batch_retry_does_not_duplicate_events`
- `test_batch_retry_does_not_duplicate_commands`
- `test_running_span_becomes_abandoned_after_crash`
- `test_duration_uses_monotonic_clock`
- `test_abandoned_duration_marked_estimated`

Stream 与完整性：

- `test_concurrent_event_producers_get_unique_stream_sequence`
- `test_stream_sequence_is_monotonic_per_trace`
- `test_sse_resume_has_no_gap_or_duplicate`
- `test_sse_uses_persisted_sequence_not_process_memory`
- `test_queue_drop_marks_trace_partial`
- `test_missing_span_end_marks_trace_partial`
- `test_complete_trace_has_no_integrity_flags`
- `test_metrics_report_incomplete_telemetry`
- `test_ui_exposes_incomplete_trace`

递归抑制与单向 OTel：

- `test_observability_store_does_not_trace_itself`
- `test_otlp_export_does_not_create_recursive_spans`
- `test_trace_api_store_read_is_suppressed`
- `test_retention_job_does_not_trace_itself`
- `test_manual_http_instrumentation_creates_one_server_span`
- `test_otel_auto_and_manual_cannot_be_enabled_together`
- `test_internal_sqlite_sink_is_not_otel_exporter`
- `test_otel_adapter_is_one_way`
- `test_internal_recorder_is_single_source`

隐私、HMAC 与采样：

- `test_raw_error_message_is_not_persisted`
- `test_hmac_key_id_recorded_without_key`
- `test_content_payload_is_rejected`
- `test_artifact_ref_does_not_inline_content`
- `test_metadata_diagnostic_and_otlp_sampling_are_distinct`
- `test_trace_flags_do_not_control_local_recording`

Access、API 与 Registry：

- `test_observability_api_defaults_disabled`
- `test_caller_scope_hash_alone_does_not_grant_access`
- `test_local_admin_can_access_observability`
- `test_unauthorized_and_missing_trace_both_return_404`
- `test_sse_uses_same_access_policy_as_trace_detail`
- `test_metrics_access_is_restricted`
- `test_same_span_id_in_different_traces_is_not_ambiguous`
- `test_span_detail_requires_trace_id`
- `test_attribute_registry_interprets_trace_version`
- `test_trace_compare_rejects_incompatible_registry`

为保持验收命令与需求清单一一对应，以下聚合用例名也必须存在（可以调用上述更细粒度 fixture，但不能只留在文档中）：

- `test_remote_parent_link_mode`
- `test_trace_context_never_changes_authorization`
- `test_concurrent_event_sequence`
- `test_sse_resume_without_gap`
- `test_stream_sequence_persisted_by_writer`
- `test_queue_drop_marks_partial`
- `test_missing_span_end_marks_partial`
- `test_otlp_export_does_not_recurse`
- `test_manual_and_auto_http_instrumentation_are_mutually_exclusive`
- `test_caller_scope_hash_not_authorization`
- `test_trace_and_sse_share_access_policy`
- `test_span_detail_uses_trace_and_span_id`

## 21. 风险与缓解

| 风险 | 影响 | 缓解/待决策 |
| -- | -- | -- |
| `ALIGNMENT_BENCHMARK_PENDING` | 将运行Telemetry误当质量证据 | v1.8只验收基础设施；禁止推造Accuracy/F1；最迟v1.9补人工Gold |
| Trace State过大 | 内存/DB/UI失控 | 不存 State，严格 cap、聚合、分页、虚拟化 |
| Prompt/Code泄漏 | 安全与合规事故 | v1.8无Content模式；allowlist+Redactor+ArtifactRef，原文拒绝 |
| 高基数属性 | Metrics爆炸 | Registry分离 Trace属性和Metrics label；ID不作label |
| SQLite写竞争 | 业务Store延迟 | 独立DB、单writer、batch/WAL/busy、非阻塞队列 |
| Queue堆积/Event丢失 | Trace不完整 | 有界优先级drop、reserved terminal、drop metric、incomplete标志 |
| Parent/Child断裂 | 时间线错误 | contextvars+显式边界参数、ID校验、orphan Event |
| 嵌套操作重复Root | Trace碎裂、重复计数 | `start_span_or_root`唯一入口，有本地parent只建Child |
| Command乱序/重放 | 生命周期倒退、重复Event | command_id幂等、sequence/terminal guard、pending terminal |
| Resume/Retry关联错误 | 错误归因 | 独立Trace + typed SpanLink，Run ID不冒充Trace ID |
| OTel约定变化 | 属性不兼容 | 版本化 `cra.*`、记录semconv、稳定HTTP优先、adapter隔离 |
| External Exporter不稳 | 请求失败或积压 | 默认关闭、bounded retry/circuit breaker、本地先落、业务隔离 |
| 手动与自动插桩重复 | 双Span与错误延迟 | 默认manual，配置互斥，Internal Recorder唯一入口 |
| Observability自我递归 | 无限Span/Queue爆炸 | contextvar suppression覆盖Store/export/retention/API read |
| Trace/业务状态不一致 | 误判运行结果 | 业务Store权威、Trace best-effort、inconsistency metric |
| 前端大Trace | 卡顿/浏览器崩溃 | 后端cap、pagination、virtualization、层级聚合 |
| Retention误删 | 诊断缺失或删错库 | 独立DB、dry-run/count、按Trace FK、小批事务、绝不触碰业务Artifact |
| 可观测系统自身故障 | 增加业务失败率 | Noop fallback、全边界catch、故障注入、独立健康指标 |
| 错误always-sample泄密 | 错误路径暴露内容 | 只强制metadata，不提升content，错误模板化 |
| Caller scope不足 | Trace越权 | 与业务授权绑定；未建立真实认证前默认保守拒绝跨scope |
| HMAC Key丢失/轮换 | 关联中断或低熵泄漏 | Secret-aware key、key_id、缺Key fail closed、按retention销毁 |
| Cost不准确 | 误导预算 | 版本化价格表；未知为null；与Provider账单明确区分 |

待冻结决策：v1.7 tag、OTel精确兼容版本、Trace DB默认启用与路径、metadata/diagnostic retention、remote parent在可信部署是否允许continue、slow阈值、queue/batch/flush与pending-terminal窗口、local-admin身份来源、HMAC key retention、OTLP部署方式、pricing profile来源、Trace Explorer单Trace上限。

## 22. Definition of Done

v1.8.0 只有同时满足以下条件才完成：

1. 基线明确区分 v1.7 `implementation complete` 与 `ALIGNMENT_BENCHMARK_PENDING`；v1.8报告不把Trace指标解释为Alignment Accuracy/F1/Calibration。
2. `TraceContext`、`RecordingDecision`、`TraceRecord`、`SpanRecord`、`TraceEvent`、`SpanLink`、`TraceArtifactRef`、`MetricSnapshot`、`TracePersistenceStatus`、`TraceExportJob` 和 `TelemetryCommand` 均严格校验、版本化并有大小测试。
3. 只有没有有效本地parent的操作创建Root；Agent/Alignment/Analysis/API内的Retrieval、Provider和Tool只创建Child Span，不产生第二Root。
4. 同步API、后台Analysis/Agent/Alignment、独立Index和独立Retrieval严格遵守第6.2节Root Policy；202后台Trace有`queued_from` Link。
5. W3C Remote Parent支持`continue|link|ignore`且默认`link`；非法Context安全忽略，完整header不落库，远端Context永不改变授权。
6. `TelemetryCommand.command_id`幂等；Span/Trace生命周期不能逆转，duplicate terminal幂等，conflicting terminal被拒绝并计数。
7. end-before-start按有界pending规则确定性处理；进程崩溃后running Span转abandoned并带完整性flag。
8. `started_at/ended_at`使用UTC wall clock，正常`duration_ms`使用monotonic/perf counter；abandoned估算设置`duration_estimated=true`。
9. Trace/event counts由single writer最终化或查询计算，业务线程不并发竞争更新。
10. Event的`stream_sequence`由SQLite single writer在持久事务内分配，同Trace唯一递增；SSE只用该值作为`Last-Event-ID`。
11. Queue drop、Store failure、Crash、missing start/end、sequence gap、orphan和export incomplete会把Trace标为partial/unknown并显示integrity flags；complete Trace无flag。
12. Metrics从不完整Trace聚合时返回`telemetry_complete=false`与完整性统计，不将partial/unknown当成精确业务事实。
13. `suppress_observability()`覆盖Observability Store、migration、flush、retention、OTLP、health/error处理和Trace API底层Store read；这些路径不会自我插桩。
14. Internal Recorder是唯一业务Trace入口，数据只单向流向Local SQLite Persistence Sink与OTel Adapter；不存在OTel回写SQLite/Internal闭环。
15. `OBSERVABILITY_HTTP_INSTRUMENTATION=manual|otel_auto`配置互斥，默认manual；同一HTTP/DB/Client operation不能由手动和自动插桩重复建Span。
16. 本地metadata、diagnostic metadata和OTLP sampling由`RecordingDecision`分离；`trace_flags`不控制本地持久化。
17. 计划和实现不宣称首版Tail Sampling；slow/error只能保留已采集metadata，不能恢复此前未采集Child或业务内容。
18. v1.8不支持Content Capture；Trace DB不保存Query、Prompt、Response、源码、论文、Secret、Authorization、Cookie、connection string、Checkpoint、完整State或原始异常文本。
19. Error只保存注册模板、error code、安全exception type和可选HMAC hash；Stack、SQL参数、Provider response和用户路径不落库。
20. HMAC Key来自Secret-aware配置，Key不落库/API/日志；记录`hash_key_id/hash_algorithm`，缺Key时低熵字段fail closed，轮换/销毁策略有测试。
21. 原始业务内容只能通过`TraceArtifactRef`引用并由原业务权限读取；Trace API/UI不内联Artifact。
22. Attribute Registry记录introduced/deprecated/removed/replacement/value schema；旧Trace按自身版本解释，Compare输出compatible/partial/incompatible。
23. SQLite Persistence状态与OTLP Export Job完全分离；SQLite不被命名或实现为OTel Exporter。
24. Trace Store使用独立编号migration、WAL、bounded queue/batch、短事务、abandoned处理和显式retention，不修改业务Schema。
25. Queue overflow、command/batch retry、Store unavailable、OTLP failure、shutdown flush和retention均有故障测试；业务返回和状态不受影响。
26. 六类业务操作均可在独立入口形成Root或在嵌套入口形成Child；Parent/Child、Link、orphan和aggregated tree可重建。
27. Retrieval明确显示Sparse、Dense、Preliminary RRF、Graph、Final RRF、Reranker和Context阶段，不改变排序。
28. Provider、Tool、Database、Checkpoint和Cache有受限Child Span/Event，Token/cache/fallback/timeout可解释且无敏感内容。
29. Resume、Retry、enqueue和Tool reuse使用正确typed Link；run/request/trace/checkpoint ID可关联但职责不混淆。
30. ResearchRunStore/AlignmentStore仍是业务权威，Checkpointer仍是恢复权威；Trace缺失不能触发从头执行或业务状态变化。
31. `OBSERVABILITY_API_ENABLED`默认false；启用后统一`ObservabilityAccessPolicy`至少要求local admin/authenticated caller/repository membership，caller scope hash不授权。
32. Trace List、Detail、Span、Events、SSE、Metrics和Compare使用同一Access Policy；无权与不存在统一404，不泄露Trace存在性。
33. Span Detail使用`GET /observability/traces/{trace_id}/spans/{span_id}`和复合Store key；相同span_id在不同Trace不混淆。
34. SSE支持持久sequence、Last-Event-ID、无gap/duplicate重连、backpressure和terminal close；连接失败/断开不影响Run。
35. Trace Explorer明确显示complete/partial/unknown、abandoned、gap/drop/store failure/orphan/missing start/end，不把不完整Trace画成完整链路。
36. Trace Compare先检查Registry、Graph、Operation Taxonomy、Model/Scorer Profile、Sampling和Completeness；不兼容只能并排展示，不声明回归。
37. 在线Metrics labels保持低基数；系统、Retrieval、Agent、Provider、Alignment指标完整，未知Provider成本返回null。
38. Noop Recorder P95调用开销与metadata模式端到端P95增量达到第17节冻结目标；Trace故障不增加业务失败率。
39. v1.8.0-c拆为c1/c2/c3；每个子阶段分别通过Recorder On/Off等价、隐私扫描、性能和受影响旧功能回归。
40. Recorder On/Off时业务结果、Retrieval排序、Run终态、Lease/Cancel、Checkpoint恢复、Alignment Decision/Deployment和Artifact均保持等价。
41. Replay仅产生timeline/compare/checkpoint link/manifest readiness，不自动执行历史Run。
42. 自动测试不访问网络、不发送OTLP、不下载组件；完整后端测试、前端测试/build和`scripts/validate.sh`通过，性能/故障注入结果写入验收文档。
43. v1.4事实ID/数据库、v1.5 Retrieval排序/generation、v1.6 Agent状态/Checkpoint/API、v1.7 Alignment算法/Store/Deployment/Review以及旧Analysis/报告/前端保持兼容。

本文件只定义 v1.8 后续实施方案；本轮未实现 TraceRecorder、OpenTelemetry、Observability SQLite、middleware、业务插桩、API、SSE、Metrics 或 Trace Explorer。
