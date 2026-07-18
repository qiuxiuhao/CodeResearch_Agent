# CodeResearch Agent v1.8.0 基线

验收日期：2026-07-18
用途：v1.9.0 Evaluation、Bad Case 与 Regression Loop 的事实基线

## 1. 基线身份与可复现性

| 项目 | 实际值 |
| -- | -- |
| Branch | `upgrade/v1.7-paper-code-alignment` |
| HEAD Commit | `25edd020e533baa90bee432f4a6251fc0fac531b` (`feat: implement paper-code alignment v1.7.0`) |
| Tag | HEAD 无 tag |
| 工作区 | 非干净；v1.8 后端、前端、测试、文档和 `pyproject.toml` 均为未提交修改/新增文件 |
| Git 事实结论 | HEAD 仍是 v1.7 提交；v1.8 是已通过本地验收的工作树实现，不是独立 commit/tag，也不能描述为稳定发布基线 |
| Shell Python | `/Users/qiu_star/miniforge3/bin/python`，Python 3.13.13；未安装 pytest |
| 项目验证 Python | `/Users/qiu_star/miniforge3/envs/code-research-agent/bin/python`，Python 3.11.15 |
| Node.js | `/Users/qiu_star/.nvm/versions/node/v24.15.0/bin/node`，v24.15.0 |
| 声明版本 | 工作树中的 `pyproject.toml` 与 FastAPI app 为 1.8.0；前端 package 版本仍为 1.3.5 |

本基线的首要技术债是先将当前已验收 v1.8 工作树整理为独立 commit，并创建受保护的 `v1.8.0` tag；在此之前，任何 v1.9 Evaluation Run 都必须同时记录 HEAD SHA 与工作树 patch/content hash，不能只记录 `25edd02` 并声称它包含 v1.8。

## 2. 环境与依赖

项目验证环境实际版本：

- FastAPI 0.139.0。
- Pydantic 2.13.4。
- LangGraph 1.2.8。
- `langgraph-checkpoint` 4.1.1。
- `langgraph-checkpoint-sqlite` 3.1.0。
- httpx 0.28.1。
- pytest 9.1.1。
- PyMuPDF 1.28.0。

前端实际安装版本：React/React DOM 19.2.7、TypeScript 5.9.3、Vite 7.3.6、Vitest 3.2.7、Mermaid 11.16.0。

工作树在 `pyproject.toml` 中声明了 OpenTelemetry 1.44 可选 extra，但本环境没有安装 `opentelemetry-api`、SDK 或 OTLP HTTP Exporter；Qdrant Client 与 FastEmbed 也未安装。因此本轮验收覆盖 Internal Recorder、SQLite、Noop/InMemory 和 OTLP-disabled fallback，不包含真实 OTLP Collector、Qdrant 或真实 Dense 模型连通性。

## 3. 验收命令与结果

| 命令 | 实际结果 |
| -- | -- |
| `python -m pytest -q` | 失败：Shell Python 3.13.13 没有 pytest；属于解释器选择问题 |
| `conda run -n code-research-agent python -m pytest -q` | 通过：373 passed，6 warnings，54.27s |
| `npm --prefix frontend test` | 通过：17 个测试文件、30 项测试 |
| `npm --prefix frontend run build` | 通过：TypeScript typecheck、3697 modules、Vite production build 和 build contract 均通过 |
| `bash scripts/validate.sh` | 通过：脚本切换到 Conda Python，后端 373 passed；前端 30 passed；build 通过 |
| `python scripts/benchmark_observability.py --iterations 2000` | 通过：Noop P95 0.0003ms；metadata enqueue P95 0.0823ms；26,290.68 commands/s |

Warnings 为既有 FastAPI/Starlette TestClient 的 httpx 弃用提示、PyMuPDF/SWIG 弃用提示、npm `whatwg-encoding` 弃用提示和 Vite 大 chunk 提示。本轮只记录，不修改功能代码。

## 4. v1.8 Trace 合同

`backend/app/observability/schemas.py` 已实现严格 Pydantic v2 模型，包括：

- `TraceContext` 与分离的 `RecordingDecision`。
- `TraceRecord`、`SpanRecord`、`TraceEvent`。
- `SpanLink`、`TraceArtifactRef`、`MetricSnapshot`。
- `TracePersistenceStatus` 与独立 `TraceExportJob`。
- 幂等队列合同 `TelemetryCommand`。
- 只读 `ReplayManifest`；其 `execution_requested` 固定为 false，v1.8 不执行 Replay。

Schema 使用 `extra="forbid"`、受限 `JsonValue`、时间/状态/大小约束。记录模式只有 `none|metadata|diagnostic_metadata`，没有 Content Capture。

Trace 完整性显式区分 `complete|partial|unknown`，Integrity Flag 包括 missing start/end、sequence gap、queue drop、store failure、process crash、orphan 和 export incomplete。正常 duration 由 monotonic/perf-counter 计算；crash 后 abandoned duration 只能估算并标记 `duration_estimated=true`。

## 5. Recorder、Queue 与 Store

`TraceRecorder` 是业务代码唯一 Trace 写入口。业务调用先形成经过 Attribute Registry、Redactor 与 Sampler 校验的 `TelemetryCommand`，再进入有界非阻塞队列。SQLite single writer 负责：

- 按 `command_id` 幂等应用。
- 防止生命周期逆转或冲突终态覆盖。
- 有界处理 end-before-start。
- 在同一短事务中为 Event 分配 Trace 内唯一递增的 `stream_sequence`。
- 最终化 span/event count 与完整性。
- 崩溃后将长期 running Span/Trace 标记 abandoned。

独立数据库为 `data/observability.sqlite3`，migration 包含 traces、spans、commands、pending terminals、events、stream sequences、links、artifact refs、metric snapshots、persistence status 和 external export jobs。SQLite 使用 WAL、foreign keys、busy timeout、短事务和显式 retention；它不是业务事实源。

Queue/Store/Exporter 失败采用 best-effort + Noop/failure counter，不能回滚或改变业务事务。`suppress_observability()` 覆盖 Observability DB、migration、flush、retention、OTLP 和 Trace API 底层读写，防止自我递归插桩。

## 6. Root、Context 与 Link

实际 Root Policy 为：只有不存在有效本地 parent 时才创建 Root。同步 API 是 `api_request` Root；202 后台 Analysis、Research Agent、Alignment 使用独立业务 Root，并以 `queued_from` Link 关联 API Trace。独立 Index/Retrieval 可为 Root，嵌套 Retrieval、Provider、Tool、DB、Cache、Checkpoint 均为 Child Span。

W3C remote parent 支持 `continue|link|ignore`，默认 `link`：服务端创建本地 Trace，并以 `linked_from_remote` 关联合法远端 Context。Trace Context 只用于关联，不能授予 caller/repo/run 权限。Resume、Retry 与 Tool reuse 使用 typed Link，不伪造父子关系。

`request_id`、`trace_id`、业务 `run_id/task_id` 和 checkpoint ID 职责分离。ResearchRunStore/AlignmentStore 仍是业务控制面，LangGraph Checkpointer 仍是 State/恢复/Interrupt 权威，Trace 只是可删除的诊断派生数据。

## 7. Redaction、采样与 Access

默认配置为 Recorder/API/OTLP 关闭，metadata-only：

```text
OBSERVABILITY_ENABLED=false
OBSERVABILITY_API_ENABLED=false
OBSERVABILITY_DETAIL_LEVEL=metadata
OBSERVABILITY_REMOTE_PARENT_MODE=link
OBSERVABILITY_HTTP_INSTRUMENTATION=manual
OBSERVABILITY_OTLP_ENABLED=false
```

Trace DB 禁止保存 Query、Prompt、Model Response、完整代码、论文正文、上传内容、Secret、Authorization、Cookie、Connection String、原始异常文本、完整 ResearchState 和 Checkpoint Blob。需要定位原始业务对象时只保存 `TraceArtifactRef`，由原业务权限读取。

本地 metadata、diagnostic metadata 和 OTLP Head Sampling 分离；`trace_flags` 不控制本地 SQLite 记录。错误只保留稳定 error code、安全 exception type、注册模板和可选 HMAC hash。HMAC key 不落库，缺 key 时要求 HMAC 的低熵字段 fail closed。

读取面使用统一 `ObservabilityAccessPolicy`。当前没有正式认证系统，因此 API 默认关闭；启用时只把受信本机 caller 视为 local admin。Caller scope hash、自报 Header 与远端 Trace Context 都不能独立授权。

## 8. OTel、API、SSE 与 Explorer

主数据流为：

```text
业务代码 → Internal Recorder
           ├── Local SQLite Persistence Sink
           └── One-way OTel Adapter → optional OTLP HTTP
```

SQLite 不是 OTel Exporter，OTel 不回写 Internal Store。默认使用手动 HTTP middleware；自动 FastAPI/database/http client instrumentation 未启用，避免双 Span。当前环境未安装 OTel optional extra，因此真实 OTLP 路径尚未验收。

Trace API 已设计并实现 List、Detail、复合 `(trace_id, span_id)` Span 查询、Event、SSE、Metrics summary/timeseries。SSE 使用 single writer 持久化的 `stream_sequence` 作为 `Last-Event-ID`，先读 Store、再等待通知；连接断开不取消业务 Run。

前端 Trace Explorer 已提供 Trace List、Span Tree/Waterfall、Span Detail、Events、Links、Artifact refs、Live SSE 与完整性展示。它明确显示 partial/unknown、abandoned、gap/drop/store failure/orphan，不把不完整 Trace 展示为完整调用链。

## 9. 当前 Benchmark、Gold 与 Runner 事实

### 9.1 Retrieval

- `evaluation/retrieval/benchmark_v1.jsonl`：40 个 synthetic fixture case，30 Dev + 10 Locked Test。
- Gold 字段：entity IDs、chunk IDs、graph paths、relevant edge types、unresolved symbol、difficulty 和 tags。
- Fixture Builder 确定性构造 2 个 repo identity、3 个 index version 和固定 Entity/Chunk/Edge；它不是 5 个真实开源仓库。
- 指标已实现 Recall@1/5/10、MRR、nDCG@5/10、Graph Path Recall、平均/P50/P95 latency 和 fallback rate。
- `scripts/evaluate_retrieval.py` 只读取外部 prediction JSONL 并重算指标；仓库没有冻结 prediction/outcome 或质量结果，也没有统一业务 Evaluation Runner。
- 单元测试使用 Fake Embedder/Sparse Provider、Mock Reranker 和临时 SQLite；真实 Dense/Qdrant 模型未在本环境验收。

### 9.2 Research Agent

- `evaluation/agent/benchmark_v1.jsonl`：30 个 synthetic/contract fixture case，20 Dev + 10 Locked Test；其中 10 direct、15 planned、5 expected partial。
- Gold/expectation 字段覆盖 route、required/optional/forbidden tools、Evidence/Edge IDs、tool budget、sufficiency、terminal status 和 tags。
- 指标函数覆盖 Task Success、Route、Tool Selection/Arguments、Invalid Tool Call、Evidence、Citation、Replan、Recovery、Budget、Latency 和 Token。
- `fault_injection` Schema 字段存在，但当前 30 个 case 均未配置真实 fault injection。
- `scripts/evaluate_agent.py` 只评估外部 `AgentBenchmarkOutcome`；仓库没有冻结 outcome，也没有批量执行 Research Graph 的统一 Runner。

### 9.3 Alignment

- `evaluation/alignment/fixture_catalog_v1.json` 只有 4 Dev + 2 Locked 的空 pair slot，repo/paper fixture 均为 null。
- `evaluation/alignment/benchmark_v1.jsonl` 只有注释，实际 0 case、0 pair、0 positive、0 negative。
- `scripts/evaluate_alignment.py --allow-incomplete` 实测输出 `case_count=0`、`pair_count=0`。
- Candidate Recall、MRR、Pair/Selection F1、Exact Set、Abstention、Selective Accuracy/Coverage、no-implementation、Evidence、Brier/ECE 和 pair macro 的实现与手算测试存在，但没有真实人工 Gold 可产生质量指标。
- 没有双人标注、adjudication、真实 6 repo-paper pair 或 Locked quality result。稳定技术债继续为 `ALIGNMENT_BENCHMARK_PENDING`。

### 9.4 Answer/Citation

`ResearchAnswer`、Agent Draft/Validated/Final Answer、Citation Validator、Claim Verifier 和 Answer Finalizer 已实现严格结构与 Evidence membership 校验。现有测试证明非法 Citation 会被删除、定位字段由 Context 事实覆盖、无 Citation 的 Claim 会变为 unsupported/evidence-only。

当前没有独立 Answer Dataset、gold answer points、claim entailment Gold 或人工 completeness rubric。Claim Verifier 第一版主要依据有效 citation 是否存在判断支持状态，测试验证结构与引用一致性，不证明自然语言 Claim 的语义正确性。

### 9.5 Observability

当前有 30 个 Observability 单元/API/Store 测试和 `scripts/benchmark_observability.py`。覆盖 Root/Child、remote parent、command 幂等、stream sequence、完整性、Redaction、Access、API 和 SQLite；性能脚本覆盖 Noop 与 metadata enqueue。

仓库没有版本化 Trace fixture dataset、端到端 expected span tree Gold、历史性能 baseline artifact 或统一 Observability Evaluation Adapter。Trace 自身不能成为 Gold；partial/unknown Trace 只能作为不完整输入。

## 10. v1.9 可读取的评测数据边界

- Structured Index：不可变 repo/index version、Entity/Edge/Evidence/Chunk、manifest、active version 和 failure isolation。
- Retrieval：`RetrievalResult` 的 Candidate、channel metadata、latency、warning、generation/profile；Query 原文不能从 metadata-only Trace恢复。
- Research Agent：Run View/Store 中的 route、plan、Tool Observation、Evidence、Budget、Answer、terminal/retry/cancel；Checkpoint 只用于显式 Replay，不是 Gold。
- Alignment：Run/Profile/Candidate/Feature/Score/Decision/Verification/Review/Deployment；人工 Review 可作为 Gold 候选来源，但仍需独立 Gold 审核与 Dataset Version 冻结。
- Observability：Trace/Span/Event/Link/ArtifactRef、completeness 与 integrity；Trace incomplete 时派生 Metric 必须 `complete=false`。

Evaluation 不得修改上述业务 Store、Trace 或 Checkpoint，不得把系统输出、Legacy Alignment、LLM 结果、Trace count 或 accepted rate自动提升为 Gold。

## 11. 已知问题与 v1.9 兼容边界

1. v1.8 尚无独立 commit/tag；这是 v1.9 开工门禁，不得把 v1.7 HEAD 当成 v1.8 代码版本。
2. `ALIGNMENT_BENCHMARK_PENDING` 未关闭，是 v1.9-a 的优先任务。
3. Retrieval/Agent benchmark 是 synthetic fixture，缺少真实多仓库分布和冻结 outcome。
4. Answer 没有独立语义 Gold；LLM Judge 不能替代人工/确定性 Gold。
5. OTel、Qdrant/FastEmbed 与真实 Provider 路径未在当前环境验收。
6. Observability API 依赖保守本地管理员策略，不是完整认证/RBAC。
7. 前端 build 有大 chunk warning；不影响本次 build 通过，但应在后续单独优化。

v1.9 必须保持：

- v1.4 Entity/Edge/Evidence/Chunk ID 与事实库不变。
- v1.5 Retrieval 排序、generation 和结果 Schema 不被评测代码改写。
- v1.6 ResearchRunStore、Budget、Cancel/Resume 与 Checkpoint 恢复语义不变。
- v1.7 Alignment Scorer、Store、Deployment、Review 与 Legacy compatibility 不变。
- v1.8 metadata-only 隐私、Trace best-effort、completeness、Access 与业务故障隔离不变。
- CI 自动评测不访问网络、不调用付费 Provider、不覆盖 Gold 或业务状态。

本文件只记录实际检查到的 v1.8 工作树基线，不包含任何 v1.9 正式功能实现。
