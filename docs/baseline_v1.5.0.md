# CodeResearch Agent v1.5.0 基线验收记录

状态：v1.6.0 开工前冻结

验收日期：2026-07-18

事实基线：v1.5.0 / `b08eddb`

## 1. 验收范围与事实口径

本文件记录 v1.6.0 开工前对 v1.5.0 代码、测试、派生索引设计和固定 Research Query 流程的实际检查结果。所有结论来自当前工作树中的实现、现有自动测试或本轮实际执行的命令；未安装的可选依赖、未下载的模型和未运行的真实模型实验不记为已验收能力。

本轮开始时 `git status --short` 无输出，工作树干净。本轮未修改 v1.5.0 功能代码、API、数据库 Schema、前端或依赖。

## 2. Git 与运行环境

| 项目 | 实际值 |
| -- | -- |
| 分支 | `upgrade/v1.6-dynamic-research-agent` |
| Commit | `b08eddb feat: complete hybrid rag v1.5.0` |
| 项目版本 | `1.5.0` |
| Conda 环境 | `code-research-agent` |
| Python | `3.11.15` |
| Node.js | `v24.15.0` |
| LangGraph | `1.2.8` |
| langgraph-checkpoint | `4.1.1` |
| langgraph-checkpoint-sqlite | 未安装 |
| qdrant-client | 未安装 |
| fastembed | 未安装 |

`pyproject.toml` 将 `qdrant-client[fastembed]>=1.9.0,<2.0` 放在可选 `retrieval` extra 中，因此默认安装不会下载 Dense、Qdrant Sparse 或 Reranker 模型。

## 3. 完整验收结果

### 3.1 独立命令

| 命令 | 结果 | 实际摘要 |
| -- | -- | -- |
| `python -m pytest -q` | 通过 | `286 passed, 6 warnings in 52.13s` |
| `npm --prefix frontend test` | 通过 | 16 个测试文件、29 个测试全部通过，耗时 1.21s |
| `npm --prefix frontend run build` | 通过 | TypeScript 检查、Vite 构建和 build contract 均通过；3695 modules，2.82s |
| `bash scripts/validate.sh` | 通过 | 后端 286 passed；前端 29 passed；前端构建通过 |

以上 Python 命令均在 `code-research-agent` Conda 环境中执行。

### 3.2 `scripts/validate.sh` 明细

- 后端：`286 passed, 6 warnings in 52.41s`。
- 前端依赖：`npm ci` 成功，安装 272 个包。
- 前端测试：16 个测试文件、29 个测试通过。
- 前端构建：3695 modules，Vite 构建耗时 3.20s，build contract 通过。

### 3.3 已知警告

- PyMuPDF/SWIG 产生 4 条 Python builtin type 缺少 `__module__` 的 DeprecationWarning。
- Starlette `TestClient` 使用的 httpx `app` shortcut 产生 2 条 DeprecationWarning。
- `npm ci` 报告 `whatwg-encoding@3.1.1` 已弃用。
- Vite 报告部分产物压缩后超过 500 kB；构建仍成功。

这些警告均未在本轮修复。

## 4. Retrieval Schema 与内部候选

实际 Schema 位于 `backend/app/retrieval/schemas.py`，全部使用 Pydantic 严格模型和 `extra="forbid"`。

### 4.1 查询边界

- `PublicRetrievalFilter`：公开的 entity type/kind、path/path prefix、qualified name、chunk type 和 edge type 过滤条件。
- `RetrievalSearchRequest`：文本、可选 index version、query type、top-k、Graph 和 Reranker 开关；不要求 body 重复传 URL 中的 repo ID。
- `ResearchQueryRequest`：在检索请求上增加 `answer_enabled` 和 `external_text_consent`。
- `RetrievalFilter`：HTTP 层解析后形成的内部过滤器，强制包含 `repo_id` 与 `index_version_id`。
- `RetrievalQuery`：内部完整查询，带 query ID、显式 repo/version filter 和有效参数。

### 4.2 内部候选阶段

- `RawRetrievalHit`：单一 `dense|sparse|graph` 来源的 chunk/entity、原始分数、来源内 rank 和 metadata。
- `FusedRetrievalCandidate`：保留 raw hits、`preliminary_rrf`、`final_rrf`、Graph path 和贡献解释。
- `FinalRetrievalCandidate`：在 fused candidate 上保存 Reranker 原始/归一化分数、最终分数和贡献。
- 公开 `RetrievalCandidate`：返回完整文本、实体和 Chunk metadata、Evidence、各来源分数与解释。

`RetrievalScore` 实际保留 Dense、Sparse、Graph、Preliminary RRF、Final RRF、Reranker 原始/归一化分数、最终分数、来源 rank 和 contribution。

## 5. 实际检索管线

`backend/app/retrieval/retrieval_service.py` 中的执行顺序是：

```text
解析并固定 repo_id + index_version_id
→ RuleBasedQueryProfiler
→ 读取当前版本 RetrievalDocument
→ FTS generation 准备/同步
→ raw_sparse_hits + raw_dense_hits
→ Preliminary RRF（只融合 Dense 与 Sparse）
→ Graph seed selection
→ Graph expansion
→ Final weighted RRF（Dense + Sparse + Graph）
→ 可选 Reranker 与 Final RRF 融合
→ Evidence 装配
→ RetrievalResult
```

Dense 相似度与 BM25 原始分数不直接相加；两者先按各自 rank 进入 RRF。`preliminary_rrf` 拒绝 Graph hit，只用于 Graph seed；最终输出使用包含 Graph 的 `final_rrf`。

### 5.1 Query Profile

`backend/app/retrieval/query_profiler.py` 的实际分类优先级为：调用方显式类型、exact symbol/path、call chain、paper alignment、training、inference、configuration、tensor shape、architecture、implementation，最后为 general repository。分类只使用规则与正则，不调用 LLM。

实际 Profile 支持：`symbol_lookup`、`implementation_explanation`、`call_chain`、`architecture`、`tensor_shape`、`configuration`、`training_process`、`inference_process`、`paper_alignment` 和 `general_repository`。每个 Profile 固定 Dense/Sparse/Graph 权重、允许的 Edge、最大 hop、Top-K、上下文优先级以及 Hybrid/Reranker 融合权重。

### 5.2 Sparse 与 FTS5

- `backend/app/retrieval/sparse_retriever.py` 实现 SQLite FTS5 baseline 和 exact symbol/path boost。
- FTS 使用独立 `retrieval_fts.sqlite3`，不修改 v1.4 结构化事实库。
- `retrieval_fts_generations` 支持 `building`、`ready`、`stale`、`failed`、`superseded` 状态。
- 同步在事务中写 companion rows 与 FTS rows并校验计数；查询只读取 `ready` generation。
- Generation 按 repo、index version、profile 和内容哈希隔离；删除操作按 repo/version 定位。

### 5.3 Dense、Qdrant Sparse 与 Vector generation

- `backend/app/retrieval/dense_retriever.py` 定义 Embedder 和 Dense retrieval 边界。
- `backend/app/retrieval/vector_store.py` 隔离 Qdrant Local 与测试 Fake/In-memory 实现。
- `backend/app/retrieval/sync_service.py` 使用 vector profile hash、repo ID、index version 和 chunk ID 生成版本化 Point ID；payload 继续保存原始 ID 与过滤字段。
- Collection 名称使用 profile hash 短前缀，但 registry/metadata 保存并验证完整 hash，能够检测短 hash 碰撞。
- Vector manifest 实际写出 `building`、`ready` 或 `failed`；当前代码没有完整实现 FTS 同等的 `stale`、`superseded` 与 active-generation 状态机。

当前环境没有安装 Qdrant/FastEmbed，也没有下载真实 Embedding/Reranker 模型。本轮完整自动测试依赖 Fake 实现，未把真实 Dense、Qdrant BM25 Sparse 或真实 Reranker 记为运行时验收通过。

### 5.4 Graph 与 EntityChunkSelector

`backend/app/retrieval/graph_retriever.py` 从 Preliminary RRF 的实体候选选择 seed，在同一 repo/version 内查询入边和出边。Graph 仅扩展 Query Profile 允许的 Edge，最大两跳，使用 confidence、Edge 权重和 `0.65 ** hop` 衰减，并通过最佳已访问分数、fan-out 和总候选上限避免环与噪声扩散。

targetless unresolved/ambiguous edge 不参与遍历，只能作为关系说明。`EntityChunkSelector` 以 Edge evidence line、query term、现有 Dense/Sparse hit、Profile 的 Chunk 类型优先级、ordinal 和稳定 chunk ID 进行确定性选择；无 Chunk 实体仅作为 note，不进入 Reranker。

实际集成中 `GraphRetriever` 传入已有 hit rank，但没有把 Edge Evidence line 装配进 selector；因此“Evidence 行优先”已在 selector 和单元测试中存在，尚未在真实 Graph 路径中生效。

### 5.5 Fusion 与 Reranker

- RRF 公式为 `source_weight / (60 + source_rank)`，exact match 在贡献中增加固定 boost。
- Final RRF 保留 Dense、Sparse、Graph 的独立贡献和稳定 tie-break。
- `backend/app/retrieval/reranker.py` 提供 `IdentityReranker`、`MockReranker` 和可选 FastEmbed Cross Encoder。
- Reranker 不覆盖 Hybrid：最终分数是 Profile-aware 的归一化 Final RRF 与归一化 Reranker 分数加权融合。
- Reranker 不可用或失败时无损回退到 Final RRF 顺序并返回 warning。
- 实际默认 `RETRIEVAL_RERANKER_ENABLED=false`。

## 6. Context、Token 与 Citation

### 6.1 ContextBundle

`backend/app/retrieval/context_builder.py` 实现：

- 内容哈希和 entity 去重；
- 完整 function/method 优先；
- 最大实体数和 token budget；
- 单个 `ContextItem` 默认最多占预算 40%；
- query-aware 确定性窗口截取；
- 保留路径、行号、论文页码与 Evidence ID；
- 无 tokenizer 时按 CJK 约 1 token、其他文本约 `ceil(chars / 2.5)` 保守估算。

`ContextBundle` 区分 `estimated_tokens`、可选 `provider_validated_tokens` 与 `token_count_method`。`ContextBuilder.validate_provider_budget()` 可以按 Provider 实际限制从最低优先级开始确定性删除 ContextItem。

当前 `ResearchQueryService` 只调用 `build()`，尚未在固定 Research Query 路径调用 `validate_provider_budget()`；因此 Provider 前两阶段 token 校验不是当前 API 的端到端已接入能力。

### 6.2 Citation Validator

`backend/app/retrieval/citation_validator.py` 校验模型引用只能来自当前 `ContextBundle`：

- `context_id` 与 `evidence_id` 必须存在；
- entity 必须一致；
- path、line range、paper/page 等定位由事实覆盖，模型不能改写；
- 非法 citation 被移除，相应 claim 标记 unsupported；
- 全部 claim 无有效证据时置信度降至不高于 0.25，并回退 evidence-only。

Validator 不把模型结果写回结构化事实数据库。

`ResearchQueryService` 当前向 Context Builder 传递空 relationship notes，Graph note 只汇总为 warning 数量；Graph 关系说明尚未进入固定回答上下文。

## 7. Provider Runtime 与固定 Research Query

`backend/app/services/model_router.py` 的 `generate_structured()` 已支持：

- Pydantic structured output；
- JSON schema/JSON object Provider capability；
- Prompt Registry；
- 输入清洗、脱敏和长度限制；
- task-scoped 请求预算、缓存、重试和 Provider fallback；
- Schema、Evidence ID 及可选业务 validator 校验。

当前 Provider 边界声明 tool-calling capability 字段，但项目没有实现 Provider 原生动态工具调用。v1.6 Planner 应继续通过 `ModelRouter.generate_structured()` 生成受 Schema 约束的 Plan，再由本地 Tool Registry 执行，不能把任意 tool call 直接交给 Provider。

现有 `BudgetManager` 统计 task/entity/provider 请求、重试、fallback 和 cache 命中，不管理 Agent plan step、tool call、replan、tool failure 或 Agent 总 token 预算。

`backend/app/services/research_query_service.py` 的实际固定流程为：

```text
RetrievalService.search
→ ContextBuilder.build
→ 可选 ProviderAnswerGenerator
→ CitationValidator
→ ResearchResponse
```

没有 consent、Provider 不可用、回答关闭或生成失败时，服务返回 evidence-only 结果。

## 8. API 与 Feature Flag

`backend/app/api/retrieval.py` 的三个路由始终注册：

- `POST /repositories/{repo_id}/retrieval/search`
- `POST /repositories/{repo_id}/research/query`
- `GET /repositories/{repo_id}/retrieval/config`

`RETRIEVAL_ENABLED` 默认 `false`；关闭时路由稳定返回 HTTP 503 和 `retrieval_disabled`。Dense、Qdrant Sparse 和 Reranker 默认关闭，offline 默认开启。请求开始时解析并固定 repo/index version，内部 Service 始终显式携带两者。

已确认 `backend/app/main.py` 对外版本为 1.5.0，并注册上述 Retrieval router。旧分析 API、旧报告和前端不依赖 Retrieval flag。

## 9. 数据库与派生索引

| 存储 | 用途 | 本轮工作树实际状态 |
| -- | -- | -- |
| `data/structured_index.sqlite3` | v1.4 Entity/Edge/Evidence/Chunk 事实源 | 当前 `data/` 中不存在 |
| `data/retrieval_fts.sqlite3` | FTS5 派生索引 | 当前不存在 |
| `data/qdrant/` | Dense/Qdrant Sparse 派生索引 | 当前不存在 |
| retrieval manifests | Vector generation 状态 | 当前不存在 |
| `data/python_function_library.sqlite3` | 旧全局函数知识库 | 存在 |
| LLM/Image cache SQLite | 模型与图片缓存 | 存在 |

本轮 Benchmark 使用临时目录重建固定 v1.5 fixture，没有向项目 `data/` 写入运行时索引。

`RetrievalReadStore` 查询使用只读 SQLite URI，但首次 `resolve_version()` 会先调用结构化索引 migration 初始化函数。实际查询按 repo/version 读取 active 或显式 superseded snapshot。

## 10. Benchmark 与真实指标

### 10.1 数据划分

`evaluation/retrieval/benchmark_v1.jsonl` 实际包含 40 条：

- Development Set：30 条。
- Locked Test Set：10 条。

题型实际分布：11 symbol lookup、8 call chain、7 implementation、5 paper alignment、3 architecture、3 training、1 configuration、1 inference、1 tensor shape。Locked Test 的 tag 覆盖 exact symbol、中文查询英文代码、Graph path、repo/version isolation、paper alignment、unresolved negative、cycle 和 path。

### 10.2 本轮可复现 Sparse-only 结果

本轮在临时目录重建固定 fixture，并运行 `scripts/evaluate_retrieval.py --mode sparse-only`。该模式有意不启用 Dense、Graph 或真实模型，因此 Graph Path Recall 为 0，不能代表完整 Hybrid 结果。

| 集合 | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@5/10 | Graph Path Recall | 平均延迟 | P50 | P95 | fallback |
| -- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| All 40 | 0.4500 | 0.5875 | 0.5875 | 0.5750 | 0.5571 | 0.0000 | 1.481 ms | 1.241 ms | 2.143 ms | 0 |
| Dev 30 | 0.4833 | 0.6167 | 0.6167 | 0.5833 | 0.5809 | 0.0000 | 1.509 ms | 1.272 ms | 2.143 ms | 0 |
| Locked 10 | 0.3500 | 0.5000 | 0.5000 | 0.5500 | 0.4857 | 0.0000 | 1.398 ms | 1.150 ms | 3.413 ms | 0 |

当前环境没有可报告的真实 Dense 模型、Qdrant Sparse、Reranker 或完整五组 Hybrid 消融结果。自动测试证明接口、融合和 fallback 的确定性，不等同于真实模型质量验收。

## 11. 当前 LangGraph 与运行状态

- `backend/app/agents/graph.py` 构建固定线性离线 Analysis Graph，共 22 个节点，无 conditional Agent loop。
- 图使用 `StateGraph(AgentState)` 并直接 `compile()`；没有 Checkpointer、ToolNode、Planner、Executor、Interrupt 或 resume。
- LangGraph 不可用时存在 `_SequentialGraph` fallback。
- `AgentState` 是离线分析专用的大型 TypedDict，包含仓库事实、论文、LLM/VLM、图片和报告字段；不适合作为动态 Research Agent State。
- 当前 Analysis Graph 的 structured index 节点位于规则 `paper_code_align` 之后、所有 LLM/VLM 增强之前。
- 当前分析任务状态为进程内 `queued|running|completed|failed`，没有持久 checkpoint、跨进程恢复或取消状态机。

## 12. 已知问题与未验证能力

1. 当前环境未安装 Qdrant/FastEmbed，真实 Dense、Qdrant BM25 Sparse 和 Reranker 未在本轮运行。
2. `QdrantBM25SparseProvider` 构造函数要求 `cache_dir`，API factory 创建时未传入；启用 Qdrant Sparse 时异常会被可选 vector service factory 捕获并使 vector service 整体不可用。
3. Provider token 再校验方法存在，但未接入固定 Research Query 的实际 Provider 调用路径。
4. Graph relationship note 没有进入 ContextBundle；当前只形成 warning 计数。
5. EntityChunkSelector 支持 Edge Evidence line 优先，但 Graph 集成未提供这些行号。
6. Vector manifest 实际只有 building/ready/failed，没有完整 active/stale/superseded 切换。
7. FTS 与可选 vector sync 可能在首次请求路径触发，冷请求延迟和并发影响未做真实大仓库验收。
8. 可选 vector/reranker factory 会捕获宽泛异常并返回 None，配置错误与依赖缺失在 API 配置视图中不够可诊断。
9. 项目 `data/` 当前没有可直接查询的 v1.5 运行时事实库或派生索引；本轮指标来自临时 fixture。
10. 没有 Dynamic Research Agent、Agent Checkpointer、resume/cancel、受控 Tool Registry 或 Agent Benchmark。

## 13. v1.6 必须保持兼容的能力

- 不修改 v1.4 Entity、Edge、Evidence、Chunk ID 和事实语义。
- 每次 Agent run 固定 `repo_id + index_version_id`，不得在执行中跟随 active version 漂移。
- 继续复用 v1.5 `RetrievalService`、`ContextBuilder`、`CitationValidator` 和只读 Store，不复制检索算法或绕过过滤。
- Preliminary RRF、Graph expansion、Final RRF、Reranker 融合顺序保持不变。
- unresolved/ambiguous edge 不伪造成已解析事实。
- Provider 只接收受预算和 consent 允许的 Context，不接收整个仓库、整个数据库或 Secret。
- Agent 工具必须只读、Schema 受控、有结果上限，并由服务端注入 repo/version。
- Agent 输出必须保留 Evidence ID、路径/行号或论文页码，并继续通过 Citation Validator。
- Retrieval API 和固定 `research/query` API 保持可独立使用；新 Agent API 使用独立 feature flag。
- 新 Research Agent Graph 不修改、删除或重排现有离线 Analysis Graph。
- 自动测试继续使用 Fake Provider、Fake Embedder、Mock Reranker/Tool，不访问网络、不下载模型。
- 旧分析 JSON、报告、现有 API 和整个前端保持 Schema 与规范化语义兼容。
