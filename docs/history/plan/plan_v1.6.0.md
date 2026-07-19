# CodeResearch Agent v1.6.0：动态 Research Agent 开发计划

状态：开工前代码审计与设计冻结

基线：v1.5.0 / `b08eddb`

实施范围：v1.6.0-a 至 v1.6.0-f

## 1. 背景与目标

v1.5.0 已有固定单轮流程：规则式 Query Profile 决定检索参数，Dense/Sparse 经 Preliminary RRF 选择 Graph seed，Graph Expansion 后由 Final RRF 与可选 Reranker 排序，Context Builder 组织证据，固定 Answer Generator 生成回答，再由 Citation Validator 校验引用。它适合单次检索能够覆盖的问题，但不会把复杂问题拆成多个证据目标，也不会根据工具结果选择下一步或恢复中断运行。

v1.6.0 在 v1.5 之上新增独立 Dynamic Research Agent：简单问题仍走 Direct Retrieval，复杂问题才生成受 Schema 和 Tool Registry 限制的计划；前序工具 ID 通过受控 StepOutputRef 绑定到后续步骤，Executor 串行调用只读工具，Evidence Sufficiency Checker 判断证据缺口，只在明确条件下 Replan，并在预算内输出可验证的完整或 Partial Answer。HTTP 202 Run 由独立 Run Store、Lease 和受控 Coordinator 驱动，LangGraph Checkpointer只承担节点恢复。

边界如下：

```text
v1.5 fixed RAG
  一次 profile → 一次 retrieval → context → answer → citation validation

v1.6 dynamic Research Agent
  route → optional structured plan → output binding → bounded read-only tools
  → evidence assessment → bounded replan → context → draft answer
  → citation validation → claim verification → deterministic finalization
```

v1.6 不替换 v1.5 Retrieval，不把模型变成任意工具执行器，也不修改现有离线 Analysis Graph。成功标准是计划、工具、证据、预算、恢复与停止原因全部结构化、可复现、可测试。

## 2. 当前代码事实

### 2.1 可复用组件

| 实际文件/组件 | 当前能力 | v1.6 复用方式 |
| -- | -- | -- |
| `backend/app/retrieval/schemas.py` | 公开/内部查询、Raw/Fused/Final candidate、Context、Claim/Citation Schema | Agent Tool 输入输出引用现有 ID，不复制 Retrieval Schema |
| `backend/app/retrieval/retrieval_service.py` / `RetrievalService.search()` | repo/version 固定后的完整 Hybrid Retrieval | `search_hybrid`、`search_paper` 的唯一检索入口 |
| `backend/app/retrieval/query_profiler.py` | 确定性 Query Profile 与权重 | Router 特征来源；不把 Profile 当 Agent Plan |
| `backend/app/retrieval/graph_retriever.py` | 同版本一/二跳 Graph Expansion、环控制、unresolved note | Graph 类工具复用 Edge 查询和边界 |
| `backend/app/retrieval/context_builder.py` | Context 去重、预算、Evidence 与 Provider 再校验方法 | 最终上下文构建；v1.6 必须接入 Provider 前再校验 |
| `backend/app/retrieval/citation_validator.py` | Context/Evidence/entity/line/page 引用校验 | `validate_citations` 节点直接复用 |
| `backend/app/persistence/retrieval_read_store.py` | active/superseded snapshot、Chunk/Entity/Edge/Evidence 只读查询 | 受控工具的数据访问层；补充只读查询时不得改变写状态机 |
| `backend/app/services/research_query_service.py` | 固定 retrieval → context → answer → citation 流程 | Direct Route 和 partial/evidence-only fallback |
| `backend/app/llm/router.py` / `ModelRouter.generate_structured()` | Pydantic structured output、预算、缓存、重试、Provider fallback、Evidence 校验 | Planner、Replan Decision 和可选 Claim assessment 的模型边界 |
| `backend/app/llm/budget.py` / `BudgetManager` | task/entity/provider 请求计数 | 继续管理 Provider 请求；AgentBudget 独立管理步骤和工具调用 |
| `evaluation/retrieval/` | 30 Dev + 10 Locked Retrieval Benchmark 与确定性指标 | Agent Benchmark 固定 repo/version 与 Evidence gold 的基础 |

### 2.2 当前固定 Retrieval 的真实顺序

```text
raw_dense_hits + raw_sparse_hits
→ Preliminary RRF
→ Graph seed selection
→ Graph expansion + EntityChunkSelector
→ Final weighted RRF
→ optional RRF/Reranker blend
→ Context Builder
→ optional Answer Generator
→ Citation Validator
```

Agent Tool 不得绕过此顺序自行比较 Dense 与 BM25 原始分数，也不得修改 Entity、Edge、Chunk 或 active index。

### 2.3 Provider、LangGraph 与状态现状

- 当前 `backend/app/llm/router.py` 的 `ModelRouter.generate_structured()` 能返回 Pydantic 模型；Provider capability 有 tool-calling 声明字段，但项目没有 Provider 原生动态工具执行实现。
- v1.6 Planner 应输出结构化 `ResearchPlan`，工具执行只能由本地 Registry 完成。
- `backend/app/agents/graph.py` 是 22 节点固定线性 Analysis Graph，`StateGraph(AgentState).compile()` 未传 Checkpointer，也没有 ToolNode、conditional loop、Interrupt、resume 或 cancel。
- 当前 `AgentState` 保存离线分析的仓库、论文、模型和报告大对象，不适合动态研究运行。
- `pyproject.toml` 当前声明 `langgraph>=0.2.0`；实际环境已安装 LangGraph 1.2.8 和 `langgraph-checkpoint` 4.1.1，SQLite Checkpointer 包尚未安装。v1.6 实施必须把安全下限提高到 `langgraph>=1.0.10`，但本轮不修改依赖。
- 当前分析任务状态只在进程内保存 `queued|running|completed|failed`，不能作为 v1.6 checkpoint。
- 当前 `backend/app/main.py` 的异步分析任务由受控 `ThreadPoolExecutor` 执行并在 FastAPI lifespan 关闭，但进度仍由进程内 `AnalysisProgressStore` 保存；它既没有持久 Lease，也不能在服务重启后恢复。
- 当前不存在 `ResearchRunStore`、Research Run 业务表、Run Coordinator 或持久 Agent API 控制面。LangGraph Checkpointer 也尚不存在，不能把未来 checkpoint blob 当作业务 Run 查询来源。

### 2.4 v1.5 已知接入缺口

v1.6 设计必须显式处理，但本阶段不能顺手改写 v1.5：

- `ContextBuilder.validate_provider_budget()` 尚未接入固定 Research Query 的 Provider 调用路径。
- Graph relationship note 当前没有进入 ContextBundle。
- EntityChunkSelector 的 Edge Evidence line 优先级没有从 GraphRetriever 实际传入。
- 可选 Qdrant BM25 provider factory 缺少必需 `cache_dir` 参数。
- 当前环境没有真实 Dense/Qdrant/Reranker 运行时依赖和模型；Agent 自动测试必须使用 Fake/Mock。

## 3. 本阶段目标

v1.6.0 仅实现：

1. 与离线 `AgentState` 分离的 `ResearchState`。
2. 简单/复杂 Query Router。
3. Structured Planner 和严格 Plan Validator。
4. 白名单、只读、Schema 受控的 Tool Registry。
5. 顺序 Executor、Observation 和重复调用检测。
6. Query Type-aware Evidence Sufficiency Checker。
7. 有条件、有上限的 Replan。
8. Claim Verifier 与 v1.5 Citation Validator 组合。
9. 受控 Step Output Binding、运行时步骤状态和跨 Replan 工具调用复用。
10. AgentBudget、Answer Finalizer 和不可恢复的 Partial Answer。
11. 独立 ResearchRunStore、Run Lease 与 ResearchRunCoordinator。
12. SQLite Checkpoint、恢复、暂停、取消、Interrupt 边界和 retention。
13. 独立 Research Agent LangGraph 与 API。
14. 30 条固定 Agent Benchmark 和非 LLM-Judge 主指标。

## 4. 非目标

v1.6.0 明确不实现：

- Multi-Agent、Agent 间协商或并行 Agent swarm。
- 长期记忆、用户画像或跨 run 自动记忆。
- 任意 Shell、Python 代码执行、任意 URL/文件读取。
- 修改、删除或生成用户仓库文件。
- 并行 DAG Executor；第一版一次只执行一个 Step。
- 完整 Trace 前端或 Bad Case 前端。
- PostgreSQL、Redis、Celery。
- 修改 v1.5 Retrieval 排序、事实数据库 Schema 或 v1.4 ID。
- 重构、删除或插入节点到现有离线 Analysis Graph。
- 让 LLM Judge 成为 Agent Benchmark 的唯一或主要指标。

## 5. ResearchState

新增独立 `ResearchState`，建议使用 LangGraph TypedDict 配合严格 Pydantic 边界对象。Graph State 只保存小型结构、ID、计数和摘要；大文本按 ID 从现有事实/派生索引重新读取。

### 5.1 字段

| 字段 | 类型建议 | 含义 |
| -- | -- | -- |
| `state_schema_version` | `str` | State 兼容版本 |
| `graph_version` | `str` | 恢复时识别 Graph 拓扑版本 |
| `run_id` | `str` | 不可变运行 ID |
| `thread_id` | `str` | 首版等于 `run_id` |
| `parent_run_id` | `str | None` | 业务父 Run；旧 Run 终态不可被重新打开 |
| `continued_from_run_id` | `str | None` | 从某个 partial/failed Run 新建继续运行时的来源 |
| `repo_id` | `str` | 服务端解析并固定的仓库 ID |
| `index_version_id` | `str` | run 开始时固定，不随 active 漂移 |
| `query` | `str` | 原始用户问题，长度受限 |
| `query_type` | `QueryType` | 复用 v1.5 类型 |
| `route` | `direct|planned` | Router 决策 |
| `route_reason` | `list[str]` | 命中特征和可解释原因 |
| `direct_escalated_to_planned` | `bool` | Direct 证据不足后是否已进行唯一一次首次规划升级 |
| `plan` | `ResearchPlan | None` | 当前已验证 Plan |
| `plan_history_ids` | `list[str]` | Replan 历史 ID，不存完整旧 Prompt |
| `current_step_index` | `int` | 下一待执行 Step |
| `step_runtime` | `list[PlanStepRuntime]` | 当前与历史 Plan 的有界步骤运行记录；定义与运行状态分离 |
| `observations` | `list[ToolObservation]` | 有界摘要、ID、错误，不存大量完整 Chunk |
| `evidence_ids` | `list[str]` | 去重后的证据目录 |
| `seed_evidence_ids` | `list[str]` | 新 Run 显式继承且重新校验过的证据 ID |
| `entity_ids` | `list[str]` | 关联事实实体 ID |
| `evidence_sufficient` | `bool` | 最近一次评估结论 |
| `missing_evidence` | `list[str]` | 结构化缺口 |
| `draft_answer` | `DraftResearchAnswer | None` | 模型生成、尚未信任引用的草稿 |
| `validated_answer` | `ValidatedResearchAnswer | None` | Citation 与 Claim 均已验证的中间结果 |
| `answer` | `ResearchAnswer | None` | Finalizer 确定性组装的最终/部分回答 |
| `confidence` | `float` | 验证后置信度 |
| `tool_call_count` | `int` | 实际启动的工具调用数，含 timeout/failed，不含成功 Observation 复用 |
| `tool_reuse_count` | `int` | 通过 semantic tool call key 复用的次数 |
| `replan_count` | `int` | Replan 次数 |
| `tool_failure_count` | `int` | 工具失败累计数 |
| `token_usage` | `AgentTokenUsage` | Planner/Answer 输入输出/总 token |
| `status` | `ResearchRunStatus` | 运行状态 |
| `stop_reason` | `str | None` | 完成、部分、失败或取消原因 |
| `errors` | `list[AgentError]` | 有界结构化错误摘要 |
| `cancel_requested` | `bool` | 从 Run Store 最近同步的取消快照；Run Store 才是权威源 |
| `resume_count` | `int` | 成功恢复次数；`resumed` 不是持久状态 |
| `last_resumed_at` | `datetime | None` | 最近一次恢复时间 |
| `created_at/updated_at` | `datetime` | 审计时间，不参与计划逻辑 |

### 5.2 禁止进入 State 的内容

- 整个仓库、完整论文、完整数据库查询结果或大量完整 Chunk。
- Provider Secret、Authorization header、环境变量和模型私有配置。
- 完整 system/user Prompt、模型隐式推理或 chain-of-thought。
- 无上限工具输出、二进制图片/PDF、Embedding 和 Qdrant payload 全量。

Observation 只保存：`observation_id`、plan/step、`step_execution_id`、`tool_call_key`、规范化 resolved arguments hash、reuse 来源、状态、entity/chunk/evidence/edge ID、最多 2,000 字符的确定性摘要、结果计数、warning/error code、latency 和时间。需要回答时由 Context Builder 按 ID 重新装配正文。

计划定义和运行状态必须分离：`PlanStep` 是不可变计划意图，`PlanStepRuntime` 是某一 `plan_version + step_id` 的执行记录。旧 Plan 被替换后，其 runtime 和 Observation 仍保留用于审计，但不再进入当前步骤选择。

### 5.3 状态机

```text
queued
  → routing
  → planning | retrieving
  → executing | assessing | replanning
  → building_context
  → generating
  → validating
  → verifying
  → finalizing
  → completed | partial

任一非终态 → cancelling → cancelled
可恢复运行态 → paused | interrupted
paused | interrupted → 取得 Lease 后回到中断前对应运行阶段
不可恢复故障 → failed
```

可恢复非终态只有 `paused|interrupted`。不可恢复终态只有 `completed|partial|failed|cancelled`；每个终态必须有 `stop_reason`，终态 transition 原子且不可逆。`resumed` 不作为持久状态，只增加 `resume_count`、记录 `last_resumed_at`，再进入 checkpoint 指示的运行阶段。

`partial` 表示本次 Run 已结束，绝不 Resume。用户要继续时创建新 Run，以 `parent_run_id`、`continued_from_run_id` 和经过当前 repo/version 再校验的 `seed_evidence_ids` 建立关联；旧 Run 仍保持 terminal。

## 6. Router

`RuleBasedResearchRouter` 初期只使用可解释特征，不调用 LLM。优先复用 v1.5 Query Profile，再增加多目标、比较、路径和证据类型特征。

### 6.1 Direct Retrieval

满足下列条件且无复杂特征时直接检索：

- exact symbol、qualified name 或路径定位；
- 单个函数/类的实现说明；
- 单一配置项或单个 tensor shape 位置；
- 问题只有一个明确实体和一种证据目标；
- `symbol_lookup` 以及低歧义的 `implementation_explanation|configuration|tensor_shape`。

Direct Route 调用一次 `search_hybrid`，经 Evidence Sufficiency 后可直接进入 Context。若证据不足且存在明确可恢复缺口，可进行一次 Direct → Planned 升级，并设置 `direct_escalated_to_planned=true`。这是该 Run 的首次 Plan，不增加 `replan_count`；同一 Run 不允许第二次 route escalation。

### 6.2 Planned Route

下列问题进入 Planner：

- call chain、architecture、training/inference process、paper alignment；
- 两个以上实体、比较/因果/跨文件问题；
- 要求一/二跳路径、入口到输出、论文证据与代码证据配对；
- 包含多个 success criteria，单次 top-k 无法证明；
- exact 路由歧义或 Direct Retrieval 明确缺证。

Router 输出 `route`、`query_type`、命中特征和置信度。未命中复杂条件时不得“为了保险”调用 Planner。Benchmark 的 10 条 Direct case 必须全部绕过 Planner。

路由升级指标与 Replan 指标分开：`Direct Escalation Rate` 统计首次 Direct → Planned，`Replan Rate` 只统计已有验证 Plan 被新版本替换。Direct 证据充分时不创建 Plan；升级失败或已升级一次后仍不足时进入 `partial`。

## 7. Planner Schema 与验证

### 7.1 Schema

```python
class ExpectedEvidence(BaseModel):
    evidence_type: Literal["code", "graph", "paper", "config", "alignment"]
    description: str
    required: bool = True
    minimum_count: int = Field(default=1, ge=1, le=10)

class StepOutputRef(BaseModel):
    step_id: str
    field: Literal["entity_ids", "chunk_ids", "edge_ids", "evidence_ids"]
    index: int | None = Field(default=None, ge=0)
    selection: Literal["first", "all", "unique"] = "first"
    required: bool = True

class ArgumentBinding(BaseModel):
    argument_name: str
    from_step: StepOutputRef

class PlanStep(BaseModel):
    step_id: str
    ordinal: int = Field(ge=0, lt=6)
    goal: str
    tool_name: ToolName
    literal_arguments: dict[str, JsonValue] = Field(default_factory=dict)
    argument_bindings: list[ArgumentBinding] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    success_criteria: list[str]
    expected_evidence: list[ExpectedEvidence]
    max_results: int = Field(ge=1, le=30)

class PlanStepRuntime(BaseModel):
    step_id: str
    plan_version: str
    status: Literal[
        "pending", "resolving", "running", "success", "empty", "failed", "skipped"
    ]
    step_execution_id: str | None = None
    observation_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    skip_reason: str | None = None
    error_code: str | None = None

class ResearchPlan(BaseModel):
    plan_id: str
    plan_version: str
    query_type: QueryType
    goal: str
    steps: list[PlanStep] = Field(min_length=1, max_length=6)
    success_criteria: list[str]
    expected_evidence: list[ExpectedEvidence]
    assumptions: list[str] = Field(default_factory=list)
```

### 7.2 Planner 边界

- Planner 通过 `ModelRouter.generate_structured(ResearchPlan)` 调用；不执行 Provider 原生 tool call。
- Tool name 必须是 Registry 枚举；Planner 只能提供字面量或上述 `StepOutputRef`，不得生成 JSONPath、模板字符串、表达式、Python、属性链或任意对象字段访问。
- `repo_id`、`index_version_id`、run ID、超时和硬上限不允许由 Planner提供或覆盖。
- dependency 和 `from_step.step_id` 只能指向同一 Plan 中 ordinal 更小的 Step；引用 Step 必须同时进入 dependency 闭包。第一版要求线性执行，不并行调度。
- `StepOutputRef.field` 只能是 ToolObservation Contract 公开的四类 ID；Plan Validator 根据源工具 Output Contract 验证该字段存在。
- `selection=first` 或显式 `index` 产生单值；`all|unique` 产生列表。单值 Tool 参数不得绑定多值，列表参数必须校验元素类型和最大 cardinality；`index` 不得与 `all|unique` 同时使用。
- `required=true` 且源输出缺失/越界时，参数解析失败并转 Evidence/Replan/Partial，绝不传 `null`。`required=false` 缺失时省略该参数，是否允许缺省仍由目标 Tool Input Schema 决定。
- `literal_arguments` 与 `argument_bindings.argument_name` 不得重名，同一参数只能有一个来源。绑定解析后生成的完整参数必须再次通过目标 Tool Input Schema。
- Step ID、plan ID 由服务端基于 canonical plan 生成或重写，不能信任模型随机 ID。
- Plan Validator 拒绝未知工具、重复 ordinal、循环/未来 dependency 或 binding、未知输出字段、cardinality 不匹配、超过预算、空 success criteria、过宽查询和参数注入。
- Provider 不可用、未授权或结构化输出连续失败时，复杂问题使用 Query Type 对应的确定性 fallback plan；仍不能满足时返回 evidence-only Partial Answer。

### 7.3 参数绑定与运行时状态

`resolve_step_arguments` 在 Tool 执行前读取当前验证 Plan、对应 `PlanStepRuntime` 和已 checkpoint 的 Observation：

1. 将 runtime 从 `pending` 改为 `resolving`。
2. 复制 `literal_arguments`，按绑定声明读取已完成 Step 的公开 ID 列表。
3. 执行 `first|all|unique|index`，应用 required 与 cardinality 规则。
4. 生成 canonical resolved arguments，并通过 Tool Input Schema 二次校验。
5. 成功后生成 `step_execution_id`，再进入 `execute_step`；失败时 runtime 进入 `failed|skipped`，不调用 Tool。

Evidence 已充分时，`mark_remaining_steps_skipped` 把当前 Plan 其余 `pending` Step 标记 `skipped` 并记录 `skip_reason=evidence_sufficient`。依赖为 `empty|failed|skipped` 时，必须按 binding required、Step success criteria 和 Replan policy 明确选择 skip、Replan 或 Partial，不能把缺失输出伪装成合法参数。

Checkpoint 恢复遇到 `resolving|running` Step 时，根据 `step_execution_id` 和 semantic tool call key 判断是否已有成功 Observation；有则恢复为 success，没有则按 Error Policy 安全重试或转 interrupted。Replan 创建新的 `plan_version` runtime 集合，旧 Plan runtime 历史只读保留。

## 8. 受控 Tool Registry

所有工具只读，输入输出 Pydantic `extra="forbid"`，由 `ToolExecutionContext` 服务器端注入 `run_id + repo_id + index_version_id + budget + trace_id`。Planner 不能请求 Shell、文件系统路径、SQL、URL、Python、任意模型或写操作。

### 8.1 公共输出与错误

```python
class ToolObservation(BaseModel):
    observation_id: str
    step_id: str
    plan_version: str
    tool_name: ToolName
    resolved_arguments_hash: str
    tool_call_key: str
    step_execution_id: str
    reused: bool = False
    reused_observation_id: str | None = None
    reused_from_plan_version: str | None = None
    status: Literal["success", "empty", "failed", "timeout"]
    entity_ids: list[str]
    chunk_ids: list[str]
    edge_ids: list[str]
    evidence_ids: list[str]
    summary: str
    result_count: int
    warnings: list[str]
    latency_ms: float
    error: AgentError | None = None
```

稳定错误码至少包括：`tool_not_found`、`invalid_tool_arguments`、`repository_not_found`、`index_version_not_found`、`index_version_mismatch`、`retrieval_disabled`、`derived_index_not_ready`、`tool_timeout`、`tool_empty_result`、`tool_busy`、`tool_internal_error`。错误必须包含 `retryable`，不得暴露 SQL、绝对敏感路径或 Secret。

### 8.2 工具清单

| 工具 | 输入 Schema 与硬上限 | 输出 | v1.5 复用 | 超时 | Mock 与主要错误 |
| -- | -- | -- | -- | --: | -- |
| `search_hybrid` | query、QueryType、公开 filter、`top_k<=30`、Graph/Reranker 受限开关 | Candidate/Evidence ID、有限摘要和 warnings | `RetrievalService.search()` | 8s | Fake RetrievalService；disabled/not-ready/busy/timeout |
| `get_symbol_source` | `entity_id` 或 exact qualified name 二选一；最多 1 实体、400 行/12k 字符 | signature/source window、path/line Evidence | RetrievalReadStore 的 entity/chunk/evidence 只读查询 | 3s | Fixture entity；not-found/ambiguous/no-source |
| `get_graph_neighbors` | `entity_ids<=10`、edge allowlist、in/out/both、每实体上限、1 hop | Neighbor entity、Edge、Evidence、unresolved note | `graph_neighbors()` 与 EntityChunkSelector | 3s | Fixture graph；invalid-edge/no-neighbor |
| `get_call_path` | source/target entity、方向、`max_hops<=2`、`max_paths<=5` | 确定性最短 CALLS/INSTANTIATES path 与证据 | RetrievalReadStore Edge + 有界 BFS | 4s | cycle/unreachable/unresolved fixtures |
| `get_model_flow` | model/class entity、方向、`max_nodes<=30` | DEFINES/CONTAINS/CALLS/INSTANTIATES/NEXT_MODULE 子图 | 现有 Entity/Edge 事实 | 4s | Fake model flow；no-flow/fanout-cap |
| `search_paper` | query、paper/filter、`top_k<=20` | Paper Chunk、page/Figure Evidence | `RetrievalService.search()` 强制 paper kind/profile | 8s | Fake paper retrieval；paper-not-indexed |
| `get_alignment` | code/paper entity 可选其一、`max_results<=20` | `ALIGNS_WITH` 边、两侧实体与证据 | Edge/Evidence read store | 3s | Alignment fixture；no-alignment |
| `inspect_config` | exact key/path/consumer entity、`max_results<=10` | config entity、source lines、CONFIGURES/USES 关系 | Sparse exact + Entity/Edge/Evidence read | 3s | Config fixture；ambiguous/no-config |

### 8.3 Registry 约束

- Registry 是不可变 `ToolSpec` 映射：name、input model、output model、handler、timeout、max result、allowed query types、error policy。
- 每次执行前以 State 中的 repo/version 覆盖任何同名外部字段；请求携带这些字段时直接拒绝，而不是静默使用。
- 工具结果再次检查所有 entity/chunk/edge/evidence 均属于 run 固定版本。
- 返回正文只为完成当前 Step 的有界 snippet；最终回答正文仍由 Context Builder 从 ID 重建。
- 单元测试通过 `MockToolRegistry` 注入固定 Observation，不调用网络、真实 Provider 或真实模型。

### 8.4 异步 Tool 与 Timeout Contract

```python
class ToolHandler(Protocol):
    async def __call__(
        self,
        tool_input: BaseModel,
        context: ToolExecutionContext,
    ) -> ToolObservation: ...
```

- 原生异步工具使用 `asyncio.timeout()` 或 AnyIO cancel scope；handler 必须传播取消，不得吞掉 `CancelledError`。
- 同步 SQLite/CPU 工具放入有界、受 Coordinator 管理的线程池，不直接阻塞事件循环。
- Python 线程通常不能强制终止。超时后立即封闭该 invocation 的 result sink；迟到返回只做资源回收，不得写 Observation、ResearchState、Run 状态或预算回补。
- 未结束的 timeout 线程任务有全局上限和每 Run 上限；达到上限返回 `tool_busy`，不能无限堆积。
- Timeout 计入实际 Tool Call 和 Tool Failure。其 Observation 默认不进入跨 Replan 成功复用；只有 ToolSpec Error Policy 明确声明安全时，特定可恢复失败才可短期去重。
- 工具返回后、接受结果前再次读取 `ResearchRunStore.cancel_requested` 和 Lease owner；已 cancelling、Lease 丢失或 invocation 已超时的结果全部丢弃。

## 9. Executor

Executor 每次 LangGraph 节点调用只执行一个 Step。参数解析是独立前置节点，流程为：

1. 每个节点入口从 `ResearchRunStore` 检查 cancel、Lease owner、terminal state 和 AgentBudget。
2. 读取 `current_step_index` 与 `PlanStepRuntime`，验证 dependency 状态。
3. `resolve_step_arguments` 按受控 binding 得到最终参数，并用目标 Tool Input Schema 二次校验。
4. 分别计算步骤审计 ID 与语义工具调用键：

```text
step_execution_id = SHA256(run_id + plan_version + step_id)

tool_call_key = SHA256(
    run_id
    + repo_id
    + index_version_id
    + tool_name
    + canonical_resolved_arguments
)
```

Canonical 参数使用 UTF-8、Unicode NFC、对象 key 排序和紧凑 JSON；拒绝 NaN/Infinity，不包含时间、随机数、Secret、trace ID 或 Plan metadata。

5. 在当前 State/checkpoint 与 Run 的 Observation 索引中查询相同 `tool_call_key` 的成功结果。命中时创建轻量 reuse Observation，设置 `reused=true`、原 Observation/Plan version，不调用 handler。
6. 未命中时把 runtime 设为 `running`，原子预留一次实际 Tool Call budget，再执行带 timeout 的异步 handler。
7. 工具返回后重新检查 cancel 与 Lease；仅当前 invocation 仍有效时写有界 Observation，并把 runtime 更新为 `success|empty|failed`。
8. checkpoint 成功后推进 Run 业务状态和 `current_step_index`；不得先对外宣称步骤完成再写 checkpoint。

确定性 `invalid_tool_arguments`、binding 错误、`tool_not_found` 和 version mismatch 不重试。`tool_busy`、临时 I/O 和 timeout 最多做一次节点级 retry，仍计入实际 Tool Call；结果为空不当作系统异常，而交给 Evidence Checker/Replan。第一版不并行执行 Step。

相同 Run、repo/version、tool 和最终参数可以跨 Plan version 复用成功 Observation；参数变化产生新 key，不同 repo/version 永远不同 key。failed/timeout 默认不复用。Reuse 不增加 `tool_call_count`，只增加 `tool_reuse_count`；`step_execution_id` 仍按新 Plan Step 生成，保证“调用复用”和“计划审计”可同时追踪。

任何可能发生在 checkpoint/Interrupt 前后的操作都必须幂等。工具全部只读；派生检索索引的 lazy sync 若由 v1.5 Service 触发，必须由其 generation 幂等保护，Agent 不自行写事实数据库。Checkpoint 不存在时不得仅凭 Run 状态猜测并从头重放已产生 Provider 成本的 Step。

## 10. Evidence Sufficiency

新增确定性优先的 `EvidenceAssessment`：

```python
class EvidenceAssessment(BaseModel):
    query_type: QueryType
    sufficient: bool
    criteria: list[EvidenceCriterionResult]
    covered_entity_ids: list[str]
    covered_evidence_ids: list[str]
    missing_evidence: list[str]
    confidence: float
    next_action: Literal[
        "resolve_next", "escalate_to_plan", "replan", "build_context", "partial"
    ]
    reason_codes: list[str]
```

### 10.1 最低证据要求

| Query Type | 最低可回答证据 |
| -- | -- |
| `symbol_lookup` | 唯一或明确多候选 Entity，加路径和行号 Evidence；歧义必须展示候选 |
| `implementation_explanation` | function/method/class source Chunk、signature/qualified name、覆盖实现范围的代码 Evidence |
| `call_chain` | 起点和终点实体、至少一条已解析 CALLS/INSTANTIATES path 及 Edge Evidence；不可达/unresolved 只能 Partial |
| `architecture` | 至少两个结构实体和一个 DEFINES/CONTAINS/IMPORTS/INHERITS/INSTANTIATES 关系；陈述范围不能超过已覆盖子图 |
| `tensor_shape` | 含 shape/reshape/维度事实的代码行与所在函数 Evidence；纯推断必须标记不确定 |
| `training_process` / `inference_process` | 入口实体、关键阶段实体和已解析关系路径；至少覆盖入口与输出/训练目标两端 |
| `paper_alignment` | 论文页码/Figure Evidence、代码路径/行号 Evidence 和有效 `ALIGNS_WITH`；缺任一侧只能 Partial |
| `configuration` | 配置 key/value 或定义位置及至少一个消费位置；只有定义时明确范围 |

Checker 首先按 ID、Edge type 和 Evidence 类型执行规则；可选模型只对“已有证据能否支持特定 claim contract”输出结构化判断，不能发明缺失 ID。模型不可用时确定性规则仍可终止。

“证据不足”不是无限搜索信号：若没有未执行 Step、没有允许的 Replan reason 或预算不足，立即 `finish_partial`。

## 11. Replan

只有以下 reason code 允许 Replan：

- `critical_tool_empty`：关键工具返回空。
- `required_evidence_missing`：最低证据未满足。
- `referenced_entity_missing`：计划引用不存在/错误版本实体。
- `path_unreachable`：当前 Graph/call path 不可达。
- `recoverable_tool_error`：工具返回可恢复错误。

禁止因“模型想再试一次”、已满足证据、相同参数重复失败或确定性非法参数而 Replan。`ReplanDecision` 必须包含 reason、已完成步骤、缺失证据、新旧 plan 差异、是否会重复调用和预算快照。

`replan_count` 只在“已有一个经过验证的 Plan，并由另一个经过验证的 Plan 替换”时增加。Direct Route 首次升级 Planner 使用 `direct_escalated_to_planned`，不是 Replan，也不消耗 Replan budget。

新计划仍经过完整 Plan Validator，`plan_version` 递增并持久化到 `research_plan_versions`。Executor 在 Step binding 完成后用 semantic `tool_call_key` 跨 Plan 复用相同成功 Observation，而不是依赖旧 step ID。若新计划没有增加有效工具/参数变化、再次产生相同失败调用、达到 2 次上限或预算不足，直接 Partial Answer。

## 12. Agent Budget

首版硬上限：

```text
MAX_PLAN_STEPS = 6
MAX_TOOL_CALLS = 10
MAX_REPLAN_COUNT = 2
MAX_TOOL_FAILURES = 3
MAX_GRAPH_HOPS = 2
MAX_RETRIEVAL_RESULTS_PER_CALL = 30
MAX_FINAL_CONTEXT_ITEMS = 8
```

另设服务器端可调但有硬上限的 Provider budget：Planner 最多 3 次结构化调用（首次 Plan 1 + Replan 2；Direct 首次升级占首次 Plan，不占 Replan），Answer 最多 1 次，Claim assessment 最多 1 次；记录 input/output/total token，但不能由请求提高硬上限。现有 `BudgetManager` 继续约束 Provider 请求，`AgentBudget` 负责 Step/实际 Tool Call/Tool Reuse/Replan/Failure/Graph/result/context 并在每个节点入口检查。

`tool_call_count` 只统计真正启动 handler 的调用，成功 Observation reuse 只增加 `tool_reuse_count`。Direct → Planned 最多一次且单独记录，不计 `replan_count`。Failed/timeout 重试每次都计入实际调用与失败预算；Plan binding 失败发生在 handler 前，不计 Tool Call，但记录 step failure 和错误码。

预算达到上限时：

1. 不启动新 Planner、Tool 或 Answer 调用。
2. 用已有 Evidence 构建有界 Context。
3. 输出 `status=partial`、具体 `stop_reason=tool_call_budget_exhausted|replan_budget_exhausted|tool_failure_budget_exhausted|provider_budget_exhausted`。
4. Claim/Citation 校验仍执行；没有可验证 claim 时返回 evidence-only，不把预算耗尽伪装成成功。

## 13. 独立 LangGraph 设计

新增 `build_research_agent_graph()`，不导入、修改或包裹现有 `build_analysis_graph()`。最终拓扑固定为：

```text
START
  ↓
route_query
  ├── direct
  │     ↓
  │ direct_retrieve
  │     ↓
  │ assess_evidence
  │     ├── sufficient → build_context
  │     ├── 可升级且未升级 → create_plan
  │     └── 无法继续 → finish_partial
  │
  └── planned
        ↓
     create_plan
        ↓
     validate_plan
        ↓
     resolve_step_arguments
        ↓
     execute_step
        ↓
     assess_evidence
        ├── sufficient → mark_remaining_steps_skipped
        │                  ↓
        │              build_context
        ├── 有剩余步骤 → resolve_step_arguments
        ├── 允许 Replan → replan
        └── 无法继续 → finish_partial

replan
  ↓
validate_plan
  ↓
resolve_step_arguments

build_context
  ↓
generate_answer
  ↓
validate_citations
  ↓
verify_claims
  ↓
finalize_answer
  ├── 有受支持回答 → completed
  └── 证据不足 → partial
```

### 13.1 条件边

| 起点 | 条件 | 目标 |
| -- | -- | -- |
| START | 固定 | `route_query` |
| `route_query` | `route=direct` | `direct_retrieve` |
| `route_query` | `route=planned` | `create_plan` |
| `direct_retrieve` | 工具完成/empty | `assess_evidence` |
| `create_plan` | 候选 Plan 已产生 | `validate_plan` |
| `create_plan` | Provider 与 deterministic fallback 均失败 | `finish_partial` |
| `validate_plan` | Plan 合法且预算允许 | `resolve_step_arguments` |
| `validate_plan` | 初始 Plan 非法且无 fallback | `finish_partial` |
| `validate_plan` | Replan 非法/重复/超限 | `finish_partial` |
| `resolve_step_arguments` | binding 与 Tool Schema 通过 | `execute_step` |
| `resolve_step_arguments` | required 输出缺失且可 Replan | `replan` |
| `resolve_step_arguments` | 确定性非法或预算不足 | `finish_partial` |
| `execute_step` | Observation 已 checkpoint | `assess_evidence` |
| `assess_evidence` | sufficient 且有未执行步骤 | `mark_remaining_steps_skipped` |
| `assess_evidence` | sufficient 且无剩余步骤 | `build_context` |
| `assess_evidence` | Direct 不足、可升级且尚未升级 | `create_plan` |
| `assess_evidence` | 当前 Plan 有可执行 Step | `resolve_step_arguments` |
| `assess_evidence` | 已有 Plan、允许 Replan 且预算允许 | `replan` |
| `assess_evidence` | 无法继续 | `finish_partial` |
| `mark_remaining_steps_skipped` | runtime 已持久化 | `build_context` |
| `replan` | 新候选 Plan 已产生 | `validate_plan` |
| `replan` | Provider/fallback 失败 | `finish_partial` |
| `build_context` | 有可用 Context 且允许回答 | `generate_answer` |
| `build_context` | 无可回答 Context | `finish_partial` |
| `generate_answer` | Draft 或 evidence-only 结果 | `validate_citations` |
| `validate_citations` | 非法引用已删除 | `verify_claims` |
| `verify_claims` | Claim support 已判定 | `finalize_answer` |
| `finalize_answer` | 至少一个重要 Claim 有支持 | completed END |
| `finalize_answer` | 无支持或只能不确定回答 | partial END |
| `finish_partial` | Finalizer 组装已有证据与 stop reason | partial END |

### 13.2 横切取消与持久化顺序

每个节点入口和 Tool 返回后都实时读取 `ResearchRunStore.cancel_requested`，不能只相信 checkpoint 中的旧 State 快照。取消统一为 `非终态 → cancelling → cancelled`；节点看到 cancelling 后不启动新 Provider/Tool，完成 checkpoint 与清理后才原子写 cancelled。

节点完成顺序固定为：校验输出 → 写 LangGraph checkpoint → 更新 ResearchRunStore 的 API 业务状态。Run Store 更新失败时 Coordinator 从最近 checkpoint 重建业务视图；Checkpoint 写失败时不得推进业务状态或接受 Tool 结果。

Router/Plan Validator/Evidence 条件函数只读 State，不做外部副作用。`resolve_step_arguments` 只解析受控 ID binding；`finalize_answer` 只做确定性文本/结构组装，不再次调用模型。

## 14. Checkpoint、恢复、取消与 Interrupt

### 14.1 调查结论

LangGraph 官方 Persistence 文档要求用 Checkpointer 编译 Graph，并通过 `configurable.thread_id` 标识线程；每个 super-step 形成 checkpoint，可用 `get_state()`/history 检查和恢复。[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

SQLite Saver 由独立 `langgraph-checkpoint-sqlite` 包提供。官方 PyPI 当前版本为 3.1.0，支持同步和异步 SQLite Saver；正式集成前必须与项目已安装 LangGraph 1.2.8 做兼容矩阵并固定精确版本或安全范围。[langgraph-checkpoint-sqlite](https://pypi.org/project/langgraph-checkpoint-sqlite/)

安全下限固定为 `langgraph>=1.0.10` 与 `langgraph-checkpoint-sqlite>=3.0.1`：LangGraph `<=1.0.9` 存在 checkpoint msgpack 不安全反序列化问题，[GHSA-g48c-2wqr-h844](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-g48c-2wqr-h844)；SQLite Checkpointer `<3.0.1` 的 metadata filter 存在 SQL injection 问题，[GHSA-9rwj-6rc7-p77c](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-9rwj-6rc7-p77c)。

LangGraph Interrupt 恢复时会从所在节点开头重新执行，因此 Interrupt 前的副作用必须幂等，并用同一 thread ID 和 `Command(resume=...)` 恢复。[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

### 14.2 ResearchRunStore：业务控制面

新增 `backend/app/persistence/research_run_store.py`，使用独立 `data/research_agent_runs.sqlite3` 和 Agent 自身编号 migration；不得修改 v1.4 structured index 数据库或事实表语义。至少包含：

```text
research_runs
  run_id PK
  thread_id UNIQUE NOT NULL
  repo_id NOT NULL
  index_version_id NOT NULL
  parent_run_id NULL
  continued_from_run_id NULL
  seed_evidence_ids_json NOT NULL
  request_hash NOT NULL
  idempotency_key_hash NULL
  caller_scope_hash NOT NULL
  status NOT NULL
  route NULL
  current_plan_id NULL
  current_plan_version NULL
  graph_version NOT NULL
  state_schema_version NOT NULL
  cancel_requested NOT NULL DEFAULT 0
  resume_count NOT NULL DEFAULT 0
  last_resumed_at NULL
  current_phase_before_pause NULL
  stop_reason NULL
  retryable NOT NULL DEFAULT 0
  created_at NOT NULL
  started_at NULL
  updated_at NOT NULL
  finished_at NULL

research_run_leases
  run_id PK/FK ON DELETE CASCADE
  lease_owner NOT NULL
  lease_token_hash NOT NULL
  lease_acquired_at NOT NULL
  lease_expires_at NOT NULL
  last_heartbeat_at NOT NULL

research_plan_versions
  plan_id PK
  run_id FK ON DELETE CASCADE
  plan_version NOT NULL
  canonical_plan_json NOT NULL
  planner_request_hash NOT NULL
  status NOT NULL
  replaced_reason NULL
  created_at NOT NULL
  UNIQUE(run_id, plan_version)
```

`research_runs` 是 API 业务状态权威源，负责 Idempotency-Key、cancel flag、状态/终态 CAS、queued/non-terminal 扫描、父子 Run、resume 计数和 retention 元数据。`research_run_leases` 是执行所有权权威源；同一 Run 最多一个未过期 Lease。`research_plan_versions` 保存每个验证 Plan 的 canonical JSON 和替换原因，不能只在 checkpoint 中保存当前 Plan。

建议平铺模型中的 `lease_owner/lease_expires_at` 在本计划中规范化到 `research_run_leases`，避免 Run 行和 Lease 行双写漂移；`ResearchRunView` 通过受控 join 返回当前 Lease 摘要。若实现选择在 `research_runs` 保留镜像字段，则镜像不得作为 claim/续租权威值，并必须在同一事务更新。

终态更新使用带允许前态的原子 compare-and-set，例如 `finalizing → completed|partial`、`cancelling → cancelled`；任何 terminal → running 更新影响 0 行并返回 `invalid_run_transition`。Plan version 写入和 Run 当前 plan 指针/状态更新位于同一短事务。

### 14.3 Checkpointer：Graph 执行状态

LangGraph Checkpointer 只负责：

- `ResearchState` 与 channel value；
- 节点 checkpoint 和 checkpoint history；
- Interrupt payload；
- 从节点边界恢复。

禁止通过 checkpoint blob 列表实现 API Run 查询、Idempotency-Key、cancel、Lease、terminal transition 或 retention 选择。使用独立 `data/research_agent_checkpoints.sqlite3`，`thread_id=run_id`，客户端不能覆盖 LangGraph config。

### 14.4 ResearchRunCoordinator

新增 `backend/app/services/research_run_coordinator.py`。本地单进程第一版采用 FastAPI lifespan + 受控 asyncio Task 管理器 + ResearchRunStore + SQLite Lease：

```text
API 在 Run Store 创建 queued
→ Coordinator 原子 claim Lease
→ 写入 routing/planning/... 业务状态
→ graph.ainvoke()/astream() 使用 thread_id=run_id
→ 定期 heartbeat 续租
→ checkpoint 成功后推进 Run 状态
→ completed/partial/failed/cancelled 原子终态
```

- Coordinator 保存每个 run ID 对应的 task handle、异常、启动时间和 shutdown event；禁止裸 `asyncio.create_task()` 后丢弃句柄。
- `claim_next()` 在一个短事务中选择 queued 或 Lease 过期且可恢复的非终态 Run，并插入/替换 Lease；两个 Coordinator 竞争时只有一个成功。
- 应用启动扫描 queued，以及 Lease 已过期的 `routing|planning|retrieving|executing|assessing|replanning|building_context|generating|validating|verifying|finalizing|interrupted` Run。只有 checkpoint 存在且版本兼容的已启动 Run可恢复；否则转 `interrupted` 并返回 `checkpoint_unavailable`，绝不静默从头重放。
- Coordinator 定期续租；续租失败立即停止接纳新节点输出，当前迟到 Tool 结果丢弃。Lease token 只保存 hash，对外 API 不返回。
- 应用关闭先停止领取新 Run，设置 shutdown signal，给当前节点有限完成时间，flush checkpoint/Run Store，释放或让 Lease 有界过期。未完成 Run 标记 `interrupted` 或保持带过期 Lease 的可恢复非终态，不能误记为业务 failed。

### 14.5 Run Store 与 Checkpoint 一致性

权威边界固定为：ResearchRunStore 管业务状态，Checkpointer 管 Graph 执行状态。节点提交协议：

1. 节点计算并严格验证 State update。
2. LangGraph 成功写 checkpoint。
3. Coordinator 以 checkpoint ID/version 和允许前态 CAS 推进 Run Store/API view。
4. Run Store 更新失败时，不重跑节点；Coordinator 读取最近 checkpoint 重建 phase、step、budget 和 terminal 候选，再幂等补写业务状态。
5. Run Store 声称 `paused|interrupted` 但 checkpoint 缺失时，Resume 返回 `checkpoint_unavailable`，不能从 START 重跑。
6. Terminal transition 幂等；重复 finalization 返回原 terminal view，不能产生第二份 Answer 或 Provider 成本。

Run API View 可以聚合 Run Store 字段和最近 checkpoint 的有界步骤摘要，但状态字段始终取 Run Store。若两者不一致，响应增加 `run_checkpoint_inconsistent` warning，并由 Coordinator repair；不能隐藏不一致。

### 14.6 Resume、Pause、取消与 Interrupt

- Resume 只允许 `paused|interrupted`，必须原子获取 Lease、验证 checkpoint 存在、验证 graph/state version、固定原 repo/index version，再增加 `resume_count` 和 `last_resumed_at`。
- `completed|partial|failed|cancelled` Resume 一律返回 `resume_not_allowed`。Partial continuation 创建新 Run并保存 lineage，不修改旧终态。
- 重复 Resume 在同一 Lease owner 下幂等返回当前 Run；其他 owner 获得 `agent_run_busy`。`resumed` 不持久化，恢复后回到 `current_phase_before_pause` 或 checkpoint 对应 phase。
- Cancel API 只在 Run Store 中原子设置 `cancel_requested=true` 并把非终态状态改为 `cancelling`。Graph 每个节点入口和 Tool 返回后实时查询 Run Store；完成 checkpoint/资源回收后才 `cancelling → cancelled`。
- terminal Run 的 Cancel 幂等返回原终态，不能变为 cancelled。
- `interrupt()` 只用于明确的可恢复暂停点或测试，不放在外部调用之后；人工暂停发生在 `resolve_step_arguments`/`execute_step` 之前，状态写为 paused。
- resumed node 从头执行依赖 `step_execution_id`、semantic `tool_call_key`、Provider request hash 和 checkpoint，不得重复成功工具调用或计费。

### 14.7 Checkpoint 安全配置

- v1.6 依赖下限：`langgraph>=1.0.10`、`langgraph-checkpoint-sqlite>=3.0.1`；兼容 spike 后固定精确版本或不跨越已验证的安全上限。
- `LANGGRAPH_STRICT_MSGPACK=true` 只是防御层之一，不作为验收依据。必须验证所选 Saver 实际支持 `with_allowlist(...)` 或等价显式 serializer 配置，并应用 `allowed_msgpack_modules`。
- Allowlist 只包含 ResearchState 所需的 TypedDict/Pydantic model、enum、datetime/UUID 等明确类型。不 checkpoint Provider、callable、数据库连接、Tool handler、exception 对象、第三方任意实例或自定义反序列化 hook。
- Saver 不支持 allowlist 传播、出现仅 warning 但继续反序列化，或遇到不兼容类型退化为裸 dict 的组合均 fail closed，不能宣称满足严格 checkpoint 安全。
- Checkpoint metadata key 全由服务端枚举生成，API/Planner/Tool 输出不能控制 filter key；metadata value 也必须限长和 JSON-safe。
- State 增加 `state_schema_version`、`graph_version`。v1.6 patch 版本只添加可选字段，不重命名/删除已发布 node/字段；恢复不兼容版本返回 `checkpoint_version_unsupported`。[Backward compatibility](https://docs.langchain.com/oss/python/langgraph/backward-compatibility)

### 14.8 Retention

- queued、所有运行阶段、paused、interrupted、cancelling Run 和其 checkpoint 不自动清理。
- completed 默认保留 7 天；partial/failed/cancelled 默认 30 天。Idempotency-Key hash 至少保留到对应 Run retention 到期，避免同 key 在可查询期被重新使用。
- 清理先在 Run Store 标记 retention lease，确认无有效 Run Lease/Resume，再删除 checkpoint、plan history 和 Run 行；部分删除需可重试并报告不一致。
- continuation Run 不延长或删除父 Run 的 retention；必要 Evidence ID 来自 immutable index version，不复制大文本。
- v1.6 只实现本地 SQLite；多进程/多主 Coordinator 和 PostgreSQL Saver 留到 v2.0。

## 15. Claim 与 Citation 验证

固定顺序改为：

```text
build_context
→ generate_answer
→ validate_citations
→ verify_claims
→ finalize_answer
```

建议区分三个边界模型：

- `DraftResearchAnswer`：模型原始结构化草稿，citation 尚不可信，绝不直接返回用户。
- `ValidatedResearchAnswer`：非法 citation 已删除、定位字段已由事实覆盖，每个 Claim 标记 `supported|partially_supported|unsupported` 和合法 citation ID。
- `ResearchAnswer`：AnswerFinalizer 的用户可见结果及完整结构化 unsupported 字段。

### 15.1 CitationValidator

复用并扩展 v1.5 `CitationValidator`，先检查：

1. citation ID 格式与唯一性。
2. `context_id/evidence_id/entity_id` 是否真实属于本次 ContextBundle。
3. path、line range、paper/page 是否被模型改写；最终值只取事实。
4. 非法引用全部删除，并记录 reason code；不得让 ClaimVerifier看到伪造定位。

### 15.2 ClaimVerifier

只基于合法 Citation、EvidenceAssessment 和 Context 判断：Claim 是否被证据支持、是否仅部分支持、范围是否超出已覆盖事实、是否缺少 Query Type 要求的证据类型。确定性 ID/类型规则优先；可选模型只能在已验证 catalog 内判断，不能恢复被删除 citation 或生成新 Evidence。

### 15.3 AnswerFinalizer

`AnswerFinalizer` 不调用模型，确定性组装最终正文：

- supported Claim 保留并附合法 citation。
- partially supported Claim 改为明确的范围限定或不确定表达，不能保留原来的无条件结论。
- unsupported 确定性结论从用户可见正文移除，但原 Claim、原因和缺失证据继续在结构化 `unsupported_claims` 中暴露。
- 所有重要 Claim 都无效时返回 evidence-only `partial`，confidence 降级并保留可验证 Evidence 列表。
- Claim/Citation/Finalizer/模型解释永不写回 v1.4 事实数据库或 KnowledgeEdge。

## 16. Agent Benchmark

### 16.1 数据与划分

首版固定 30 条，建议 20 Dev + 10 Locked Test：

- 10 条 Direct Route：exact symbol、单函数实现、配置、tensor shape。
- 15 条 Planned Route：call chain、architecture、training/inference、paper alignment、多实体比较。
- 5 条证据不足/失败：unresolved path、空结果、可恢复工具失败、预算耗尽、无 Provider。

Locked Test 至少覆盖：Direct bypass、两步/多步 Plan、call path、paper alignment、repo/version 隔离、unknown tool rejection、recoverable failure、Partial Answer、citation invalid 和 checkpoint resume。Locked Gold 只人工维护，修改 ID、expected route/tool/path/evidence 或 fault schedule 必须升级 benchmark version。

```json
{
  "benchmark_schema_version": "1",
  "id": "agent-case-001",
  "split": "dev",
  "repo_id": "repo_...",
  "index_version_id": "idx_...",
  "query": "从训练入口到模型 forward 的调用路径是什么？",
  "query_type": "training_process",
  "expected_route": "planned",
  "required_tools": ["get_call_path"],
  "optional_tools": ["search_hybrid", "get_graph_neighbors"],
  "forbidden_tools": ["inspect_config"],
  "allowed_tool_orders": [["search_hybrid", "get_call_path"]],
  "required_evidence_ids": ["ev_..."],
  "required_edge_ids": ["edge_..."],
  "expected_sufficient": true,
  "max_tool_calls": 4,
  "expected_terminal_status": "completed",
  "fault_injection": null,
  "tags": ["call_path", "training"]
}
```

`allowed_tool_orders` 只作为诊断提示，不要求唯一顺序。只要不同工具路径满足 Required Evidence、禁止工具、预算和终态要求，就可以 Task Success；Tool Exact Match 不直接决定 Task Success。

### 16.2 指标

主要成功标准按优先级为：

```text
Task Success
Required Evidence Coverage
Forbidden Tool Call Rate
Budget Compliance
Citation Validity
Terminal State Correctness
```

- Task Success Rate：Required Evidence、forbidden tool、预算、citation 和 expected terminal state 全部满足；不要求唯一工具顺序。
- Required Evidence Coverage：命中的 required evidence/edge 与 Gold 的覆盖率。
- Forbidden Tool Call Rate：调用 forbidden tool 的 case/调用比例，目标为 0。
- Budget Compliance：未越过 case 与全局硬上限的比例，目标 100%。
- Terminal State Correctness：实际 terminal 与 expected terminal 一致。
- Route Accuracy：Direct/Planned 与 gold 一致。
- Plan Validity：通过 Schema、Registry、dependency 和预算验证的 Plan 比例。
- Tool Selection Accuracy：required/optional/forbidden set 的 precision、recall；顺序和 exact match 仅作诊断。
- Tool Argument Validity：工具参数第一次校验通过率。
- Invalid Tool Call Rate：unknown/forbidden/invalid/version-mismatch 调用占比，目标为 0。
- Average Tool Calls、P50/P95 Tool Calls。
- Replan Rate 和无收益 Replan Rate。
- Direct Escalation Rate：Direct 首次升级 Planned，单独统计且不进入 Replan Rate。
- Tool Reuse Rate：semantic key 跨 Step/Plan 成功复用次数占可复用调用的比例。
- Budget Exhaustion Rate。
- Recovery Rate：注入的可恢复错误最终达到预期 terminal state 的比例。
- Evidence Sufficiency Accuracy：与人工 sufficient/insufficient label 比较。
- Citation Validity：合法 citation / 返回 citation。
- Unsupported Claim Rate：unsupported 重要 Claim / 全部重要 Claim。
- 总延迟及 route/plan/tool/assessment/answer 分段平均、P50、P95。
- Planner、Replan、Answer 的 input/output/total token usage 和 Provider fallback。

Dev 用于规则、Prompt 和预算调试；Locked Test 只在候选版本验收运行。主要指标均由结构化 Gold 和确定性 Validator 计算，不用 LLM Judge 替代。自动 Benchmark 使用 Mock Provider/Tool；真实 Provider 结果单独记录 consent、模型 revision、缓存冷热和费用。

## 17. Agent API 设计

新路由始终注册，`RESEARCH_AGENT_ENABLED=false` 时稳定返回 HTTP 503 `research_agent_disabled`，保持 OpenAPI contract。

### 17.1 `POST /repositories/{repo_id}/research/agent/runs`

请求：query、可选 index version、可选 query type、`answer_enabled`、`external_text_consent`、受限 budget/profile overrides 和可选 `Idempotency-Key`。body 不重复 repo ID。

服务端解析并固定 version，在 ResearchRunStore 创建 `queued`，由 Coordinator 后台领取 Lease 和启动 Graph；HTTP 202 不直接在 request handler 内 `ainvoke()`。响应包含 run/thread ID、queued status、repo/version、budget snapshot、created/updated 和 links。

Idempotency 规则：

```text
相同 caller_scope_hash + 相同 Idempotency-Key hash + 相同 request_hash
→ 返回原 Run

相同 caller_scope_hash + 相同 Idempotency-Key hash + 不同 request_hash
→ HTTP 409 idempotency_key_conflict

未提供 Idempotency-Key
→ 每次创建新 Run
```

数据库只保存 Idempotency-Key hash，不保存原值。`request_hash` 覆盖 repo/version、规范化 query、query type、consent/answer 语义和有效预算/配置；query 内容不能自动充当 Idempotency-Key。Key 按已认证调用主体或明确匿名 caller scope 隔离，并至少保留到 Run retention 到期。

### 17.2 `GET /research/agent/runs/{run_id}`

返回由 ResearchRunStore 权威状态和最近 checkpoint 有界视图合成的 `ResearchRunView`：状态、route、当前 Plan/StepRuntime、Observation 摘要、Evidence ID、实际调用/reuse 预算、errors、stop reason、最终 answer/partial。不得返回完整 Prompt、Secret、checkpoint blob、Lease token 或数据库路径；不一致时明确返回 warning。

### 17.3 `POST /research/agent/runs/{run_id}/resume`

只接受 `interrupted|paused`，可附受限 resume token/确认信息。服务端原子获取 Lease，验证 checkpoint、graph/state version 和原 repo/index version，再由 Coordinator 恢复同一 thread。重复 Resume 对当前 owner 幂等；并发其他 owner 返回 `agent_run_busy`。`completed|partial|failed|cancelled` 返回 `resume_not_allowed`。

### 17.4 `POST /research/agent/runs/{run_id}/cancel`

Cancel API 只在 ResearchRunStore 原子设置 `cancel_requested=true` 并将任一非终态转为 `cancelling`。Graph 节点入口和 Tool 返回后实时读取 Store；Coordinator 完成 checkpoint/资源回收后转 `cancelled`。已 terminal Run 幂等返回原终态，不得改为 cancelled。

### 17.5 错误与状态

稳定错误码：`research_agent_disabled`、`agent_run_not_found`、`agent_run_busy`、`invalid_agent_request`、`idempotency_key_conflict`、`invalid_run_transition`、`index_version_not_found`、`index_version_mismatch`、`plan_invalid`、`step_binding_invalid`、`required_step_output_missing`、`tool_not_allowed`、`agent_budget_exhausted`、`checkpoint_unavailable`、`checkpoint_version_unsupported`、`run_checkpoint_inconsistent`、`resume_not_allowed`、`agent_cancelled`、`provider_consent_required`。沿用 `error_code/component/message/retryable/context/trace_id` 结构；Idempotency 冲突固定 HTTP 409。

API 状态：`queued|routing|planning|retrieving|executing|assessing|replanning|building_context|generating|validating|verifying|finalizing|paused|interrupted|cancelling|completed|partial|failed|cancelled`。`resumed` 不是状态；`partial` 是不可恢复终态。

## 18. 推荐目录与文件边界

### 18.1 新增

```text
backend/app/agents/research/
  state.py
  schemas.py
  budget.py
  router.py
  planner.py
  plan_validator.py
  argument_resolver.py
  tool_registry.py
  executor.py
  evidence_checker.py
  claim_verifier.py
  answer_finalizer.py
  graph.py
  nodes.py
backend/app/agents/research/tools/
  search_tools.py
  symbol_tools.py
  graph_tools.py
  paper_tools.py
  config_tools.py
backend/app/persistence/research_checkpoint.py
backend/app/persistence/research_run_store.py
backend/app/persistence/research_migrations/
backend/app/services/research_agent_service.py
backend/app/services/research_run_coordinator.py
backend/app/api/research_agent.py
tests/agents/research/
tests/fixtures/research_agent/
evaluation/agent/
scripts/evaluate_agent.py
docs/evaluation_v1.6.0.md
```

### 18.2 修改

| 文件/区域 | 作用 | 约束 |
| -- | -- | -- |
| `pyproject.toml` | 将 LangGraph 下限提高到 `>=1.0.10`，增加安全固定的 SQLite checkpoint 依赖或 `agent` extra | 不改变默认 Retrieval 模型依赖；先完成兼容 spike |
| `backend/app/main.py` | 始终注册 Agent API router | flag 只控制执行，旧路由不变 |
| `backend/app/services/analysis_options.py` 或独立 Agent settings | Agent flag、DB、预算、retention | 不把 Agent 配置写入 Analysis Graph State |
| `backend/app/persistence/retrieval_read_store.py` | 必要时增加精确 symbol/path/edge 的只读方法 | 不修改 migration/写状态机和事实语义 |
| Prompt registry | 注册 Planner/Replan/Answer structured prompts | 不允许任意 tool call Prompt |
| README/evaluation docs | Agent API、离线、checkpoint、benchmark、清理 | 只记录实际验收能力 |

### 18.3 禁止修改

- `backend/app/agents/graph.py` 的离线节点和顺序，以及现有离线 `AgentState` 语义。
- v1.4 Entity/Edge/Evidence/Chunk Schema、ID 和结构化事实 migration。
- v1.5 Dense/Sparse/Graph/RRF/Reranker 算法和现有 API 响应语义。
- 旧 JSON、报告生成和分析任务行为。
- 整个 `frontend/`。
- 用户仓库内容、任意 Shell/Python 执行能力。

Agent Run 表使用独立 Agent migration runner 和 DB，不向 v1.4 `001_structured_index.sql` 追加表，也不把 Checkpointer 自有表与业务表混为一套 Schema。

## 19. 分阶段实施

### v1.6.0-a：Agent Schema、Run Store、Benchmark 和 Mock Runner

- 输入：v1.5 Schema、Retrieval fixture、Provider structured output、现有评测框架。
- 输出：ResearchState、StepOutputRef、ArgumentBinding、PlanStepRuntime、ToolObservation、EvidenceAssessment、Run/API Schema；独立 `research_runs`、`research_run_leases`、`research_plan_versions` migration/store；20 Dev + 10 Locked Benchmark 与 Mock runner；完整状态机冻结。
- 修改文件：新增 `agents/research/state.py`、`schemas.py`、`budget.py`、`persistence/research_run_store.py`、Agent migration、`evaluation/agent/`、fixtures/tests 和评测脚本。
- 新增依赖：无；并行做 LangGraph/SQLite Checkpointer 安全兼容 spike但不接入 Graph。
- 测试：Schema round-trip、State 大小/禁用字段、Step runtime、Run terminal CAS、Lease、Idempotency hash/冲突、plan version 持久化、Gold/指标手算、无网络。
- 验收标准：30 case 全部解析且 gold ID 存在；所有 Contract `extra=forbid`；terminal 不可逆；同 Run 最多一个 Lease；Run Store 独立于 v1.4 事实 DB和 Checkpoint。
- 回滚点：删除 Agent 自身 DB/Schema/Benchmark，不影响 v1.5 和 structured index。

### v1.6.0-b：受控 Tool Registry 与参数绑定

- 输入：v1.5 RetrievalService/ReadStore、Tool Contract、StepOutputRef。
- 输出：8 个只读 typed Tool、Registry、`resolve_step_arguments`、semantic tool call key、异步 timeout contract、跨 Replan Observation reuse 和 Mock Registry。
- 修改文件：新增 `tool_registry.py`、`argument_resolver.py`、`tools/`、Executor 幂等辅助和专项 tests；只在必要时补只读 Store 方法。
- 新增依赖：无。
- 测试：正常/empty/error/timeout/late result；前序 ID binding、未来/未知字段/cardinality；semantic key 的 repo/version/参数隔离；成功跨 Plan reuse、失败默认不 reuse。
- 验收标准：Registry 外工具调用率 0；所有绑定在 handler 前解析并通过 Tool Input Schema；迟到结果不能写 State；reuse 不增加实际调用；自动测试不触发模型/网络。
- 回滚点：关闭 Agent Tool 层并删除 Agent binding/cache；v1.5 Service 不变。

### v1.6.0-c：Router、Structured Planner 和 Plan Validator

- 输入：Query Profile、Tool Registry/Output Contract、ModelRouter structured output、Benchmark route/plan gold。
- 输出：RuleBasedResearchRouter、Direct escalation、ResearchPlan Prompt、deterministic fallback Plan、dependency/binding-aware Plan Validator。
- 修改文件：新增 `router.py`、`planner.py`、`plan_validator.py`、Prompt 和 tests。
- 新增依赖：无。
- 测试：简单问题不进 Planner；Direct 只升级一次且不计 Replan；复杂合法 Plan；unknown tool、未来 dependency/binding、未知字段、循环、超步数、repo/version 注入、Provider invalid JSON/fallback。
- 验收标准：10 个 Direct case 初次全部绕过 Planner；所有执行 Plan 100% 通过 Registry/参数/依赖/binding/预算；Direct escalation 与 Replan 计数严格分离。
- 回滚点：关闭 Planner，保留 Direct Retrieval/evidence-only。

### v1.6.0-d：Executor、Evidence、Replan 与 Answer Finalizer

- 输入：有效 Plan、resolved arguments、Registry、State/StepRuntime、Query Type 证据规则。
- 输出：顺序 Executor、runtime 状态、Observation reuse、EvidenceAssessment、受限 Replan、`mark_remaining_steps_skipped`、Context/Answer 节点、Citation → Claim → Finalizer、不可恢复 Partial、独立 Graph（内存 checkpointer 测试）。
- 修改文件：新增 `executor.py`、`evidence_checker.py`、`claim_verifier.py`、`answer_finalizer.py`、`graph.py`、`nodes.py` 和 tests。
- 新增依赖：无。
- 测试：empty/异常/timeout、binding missing、重复/reuse、充分后 skipped、不足继续、Replan/预算、partial 终态、Citation 先于 Claim、unsupported 可见正文移除。
- 验收标准：一次只执行一个 Step；硬预算不超限；旧 Plan runtime 可审计；Partial 不可 Resume；最终正文无 unsupported 确定性结论。
- 回滚点：Agent flag 关闭；独立 Graph 不影响 v1.5 fixed RAG 或 Analysis Graph。

### v1.6.0-e：Checkpointer、Coordinator、恢复、取消与安全

- 输入：独立 Graph、ResearchRunStore、幂等 Executor、兼容/安全 spike 结论。
- 输出：安全 SQLite Checkpointer、ResearchRunCoordinator、managed task handles、Run Lease/heartbeat、queued/expired recovery、pause/resume/cancel/Interrupt、graceful shutdown、Store/Checkpoint repair 和 retention。
- 修改文件：`pyproject.toml`、新增 `research_checkpoint.py`、`research_run_coordinator.py`，修改 Graph compile/lifespan/service 和 tests。
- 新增依赖：`langgraph>=1.0.10`；固定兼容且 `>=3.0.1` 的 `langgraph-checkpoint-sqlite`。若采用 async，使用其官方 async 依赖，不新增数据库框架。
- 测试：allowlist/fail-closed、metadata key、节点中断恢复、无重复工具/Provider、两个 Coordinator 竞争、Lease 过期、服务重启、graceful shutdown、cancel polling、checkpoint/Run repair、retention。
- 验收标准：同 Run 同时一个 Lease；启动可恢复 queued/expired Run；shutdown 不误报 failed；Resume 仅 paused/interrupted；Run Store/API/checkpoint 最终一致；不安全版本不能安装。
- 回滚点：关闭 Agent API/Coordinator并保留 Run 记录；删除独立 checkpoint/Run DB 需显式确认，不影响事实和 Retrieval。

### v1.6.0-f：Agent API、Benchmark、文档和完整回归

- 输入：Research Graph、RunStore/Coordinator/Checkpoint、Answer Finalizer、30-case Benchmark。
- 输出：4 个 Agent API、HTTP 202 后台执行、Idempotency conflict、Dev/Locked 报告、操作/恢复/retention 文档。
- 修改文件：新增 API/Service，修改 `main.py` lifespan/router，README、evaluation 文档和 API tests。
- 新增依赖：无新增。
- 测试：flag 503、create/status/resume/cancel、HTTP 409 key conflict、Coordinator 集成、服务重启、terminal transition、Run/checkpoint consistency、Provider consent、evidence-only、旧 API 回归和完整验收。
- 验收标准：30 case 分别报告 Dev/Locked 的 Evidence/Terminal/Budget/Citation 主指标；四端点 OpenAPI 稳定；HTTP 202 Run 全部由 Coordinator 管理；flag 关闭不影响 v1.5。
- 回滚点：关闭 `RESEARCH_AGENT_ENABLED` 并停止 Coordinator 领取新 Run；路由仍返回 503，v1.5 fixed RAG 保持可用。

## 20. 测试计划

| 场景 | 建议测试文件/Fixture | 核心断言 |
| -- | -- | -- |
| 简单问题不进入 Planner | `test_router.py` / direct_cases | Planner 调用为 0，route reason 可解释 |
| Direct 升级 | `test_router.py::test_direct_to_planned_escalation_does_not_increment_replan`、`test_direct_route_can_escalate_only_once` | 首次 Plan 不计 Replan，只升级一次 |
| 复杂问题合法 Plan | `test_planner.py` / planned_cases | Step<=6、工具/参数/dependency 全合法 |
| Step 输出绑定 | `test_argument_resolver.py::test_step_argument_resolves_previous_entity_id` | 前序公开 entity ID 正确进入目标参数 |
| 未来/未知引用 | `test_step_reference_cannot_target_future_step`、`test_binding_field_must_exist_in_tool_output_contract` | Plan 在执行前拒绝 |
| Binding 缺失/cardinality | `test_required_step_output_missing_stops_execution`、`test_multi_value_binding_respects_tool_cardinality` | 不传 null，单/多值与 Tool Schema 一致 |
| 未知工具拒绝 | `test_plan_validator.py` | Plan 在执行前失败，tool count 不增 |
| 非法参数拒绝 | 同上 | `extra=forbid`、repo/version 注入被拒绝 |
| 工具空结果 | `test_executor.py` | Observation=empty，进入 assessment 而非系统崩溃 |
| 工具异常/timeout | 同上 | retryable 分类、failure budget、Partial |
| 跨 Replan 复用 | `test_executor_idempotency.py::test_replan_reuses_identical_successful_tool_call` | 新 StepExecution、同 semantic key、handler 不再调用 |
| 幂等隔离 | `test_changed_arguments_create_new_tool_call_key`、`test_same_arguments_in_different_repo_do_not_reuse` | 参数/repo/version 变化产生新 key |
| 失败与 reuse budget | `test_failed_observation_not_reused_by_default`、`test_reused_observation_does_not_increment_actual_tool_calls` | 默认只复用成功，reuse 单独计数 |
| 证据充分停止 | `test_evidence_checker.py` | 不执行剩余 Step/Replan |
| Step runtime skipped | `test_step_runtime.py` | 剩余步骤为 skipped，旧 Plan runtime 保留 |
| 证据不足继续 | 同上 | 明确 missing evidence，执行下一 Step |
| Replan 上限 | `test_replan.py` | 最多 2 次，第三次转 Partial |
| Tool Call 上限 | `test_agent_budget.py` | 最多 10 次，计数不可绕过 |
| Tool Failure 上限 | 同上 | 最多 3 次后停止新工具 |
| Partial Answer | `test_partial_answer.py::test_partial_is_terminal_and_cannot_resume` | stop reason/证据返回，终态不可恢复 |
| Pause/Interrupt Resume | `test_checkpoint.py::test_interrupted_run_can_resume`、`test_paused_run_can_resume` | 只允许两种非终态恢复 |
| Terminal 不逆转 | `test_terminal_run_cannot_return_to_running` | completed/partial/failed/cancelled CAS 拒绝 |
| Checkpoint 恢复 | `test_checkpoint.py` | 重启后同 run/thread/step/evidence/runtime 恢复 |
| Interrupt 幂等 | 同上 | 节点重启不重复成功工具/Provider 计费 |
| Cancel | `test_cancel.py::test_cancel_transitions_through_cancelling` | Store flag 可见，必须经 cancelling，重复 cancel 幂等 |
| 并发 resume | `test_resume_concurrency.py` | 只有一个 lease 执行 |
| RunStore 终态/取消 | `test_research_run_store.py::test_run_store_terminal_transition_is_atomic`、`test_run_store_cancel_flag_visible_to_running_graph` | 终态 CAS；运行节点读到权威 flag |
| Plan 历史 | `test_plan_versions_are_persisted` | 每个 canonical Plan/version 可审计 |
| Run/Checkpoint 一致性 | `test_run_and_checkpoint_status_consistency` | checkpoint 先写、业务状态可 repair |
| Coordinator claim | `test_coordinator_claims_each_run_once`、`test_two_coordinators_cannot_execute_same_run` | 同 Run 一个 Lease/执行者 |
| Coordinator 恢复/关闭 | `test_expired_lease_run_is_recovered`、`test_graceful_shutdown_leaves_run_resumable` | 过期 Lease 恢复；shutdown 不误报失败 |
| Idempotency-Key | `test_agent_api.py` | 同 key/hash 返回原 Run；不同 request HTTP 409 |
| repo/version 隔离 | 每个 tool test / two_repos_versions | 零跨 repo/version ID |
| Citation 先于 Claim | `test_claim_verifier.py::test_citations_are_validated_before_claims` | ClaimVerifier 只看合法 Citation |
| Answer Finalizer | `test_unsupported_claim_removed_from_visible_answer`、`test_partially_supported_claim_is_qualified`、`test_all_unsupported_claims_return_evidence_only_partial` | 无不受支持的确定性正文 |
| Checkpoint allowlist | `test_checkpoint_security.py::test_checkpoint_rejects_unapproved_msgpack_type`、`test_checkpoint_allowlist_is_applied` | 严格 allowlist 实际生效 |
| Checkpoint fail closed | `test_checkpoint_metadata_keys_are_server_controlled`、`test_unsupported_state_type_fails_closed` | metadata key 不受用户控制；未知类型拒绝 |
| Tool timeout late result | `test_tool_timeout.py::test_late_tool_result_is_discarded`、`test_timeout_cannot_write_observation_after_cancel` | 迟到结果不写 State/Observation |
| 同步 timeout task 上限 | `test_timed_out_sync_tasks_are_bounded` | 未结束线程任务有全局上限 |
| Provider 无授权/无网络 | `test_agent_fallback.py` | deterministic/evidence-only，不访问网络 |
| Analysis/v1.5 回归 | 现有全套 tests | 旧图、Retrieval API、报告和前端不变 |

自动测试全部注入 MockPlanner、MockProvider、MockToolRegistry、Fake Retriever 和临时 SQLite Checkpointer；不得调用真实模型、下载资源或访问网络。真实 Provider Agent 测试使用显式 marker、consent、预算和预配置凭据，CI 默认跳过。

## 21. 风险与缓解

| 风险 | 影响 | 缓解 |
| -- | -- | -- |
| Planner 幻觉工具 | 调用不存在或危险能力 | ToolName 枚举、Registry/参数双校验、执行前拒绝 |
| Planner 伪造前序 ID | 初始 Plan 凭空生成实体或引用任意字段 | StepOutputRef allowlist、ordinal/dependency 验证、执行前 binding |
| Binding cardinality 错误 | 列表被传给单值工具或缺失值变 null | Output Contract + Tool Input Schema 双校验；required 缺失立即停止 |
| 无意义循环 | 延迟和费用失控 | Replan reason allowlist、差异检查、次数/调用/失败硬上限 |
| 重复检索 | Replan/checkpoint 重放造成重复费用 | resolved args semantic key 跨 Plan 复用成功 Observation、Provider cache |
| State 过大 | checkpoint 慢或损坏 | 只存 ID/有界摘要；正文按 ID 重建；State size 测试 |
| Checkpoint 膨胀 | 本地磁盘增长 | terminal retention、显式清理、State 上限和 run quota |
| 工具参数注入 | 跨 repo、路径或 SQL 泄漏 | `extra=forbid`、服务端注入 repo/version、无 SQL/path/Shell 参数 |
| Checkpointer 安全/兼容 | SQL injection、反序列化或恢复失败 | LangGraph `>=1.0.10`、Saver `>=3.0.1`、显式 allowlist、metadata key 白名单、fail closed |
| Run Store/Checkpoint 分裂 | API 显示完成但 Graph 未持久化，或反之 | checkpoint 先写、Run CAS 后写、Coordinator repair、显式 inconsistency warning |
| 裸后台 Task 丢失 | HTTP 202 后异常无人接收或关机丢 Run | lifespan Coordinator、保存 task handle、Lease/heartbeat、graceful shutdown |
| Lease 双执行 | 两个 Coordinator 重复 Provider/Tool | SQLite 原子 claim、token/owner 校验、每次接受结果前校验 Lease |
| Provider 不稳定 | Plan/Answer 失败或不一致 | structured retry/cache、deterministic fallback、Partial/evidence-only |
| Evidence Checker 误判 | 过早回答或无谓 Replan | Query Type 规则、人工 gold、缺口明示、模型只作辅助 |
| 预算失控 | 长循环、Token/成本超限 | 每节点预算检查、Provider/Agent 双预算、终态 Partial |
| Interrupt 重放副作用 | 重复工具/派生同步 | 工具只读、节点边界、幂等键、Interrupt 前无非幂等操作 |
| Timeout 线程迟到写入 | Agent 已取消/超时后 State 被污染 | 封闭 result sink、返回后重查 Lease/cancel、有界线程任务 |
| Partial 被错误恢复 | 旧证据/预算被当作未结束运行 | Partial 固定终态；继续创建带 lineage 的新 Run |
| Idempotency-Key 跨主体碰撞 | 一个调用方取得另一个 Run | caller scope hash + key hash 唯一；request hash 冲突 HTTP 409 |
| Active version 切换 | 一次 run 混合版本 | 创建时固定 version，恢复验证 superseded snapshot，不跟随 active |
| v1.5 接口兼容 | Agent 接入破坏固定 RAG | 独立 router/service/graph/flag，完整旧回归，禁止修改检索算法 |
| v1.5 已知接入缺口 | Agent 上下文/真实模型能力不完整 | 在 Agent Tool/Context 契约中显式诊断，不隐瞒 fallback；分阶段单独修复并回归 |
| SQLite 本地并发 | 多进程 checkpoint 锁竞争 | busy timeout、短写事务、单进程首版；多进程/PostgreSQL 留 v2.0 |

### 21.1 待决策项

1. v1.6.0-a 兼容 spike 后固定 `langgraph>=1.0.10` 与 `langgraph-checkpoint-sqlite>=3.0.1` 的精确安全范围，并验证 AsyncSqliteSaver 的 `with_allowlist`/serializer 行为；不能仅以能导入为兼容通过。
2. Planner/Answer 的真实 Provider model ID、revision 和 token 上限必须在启用前由部署配置固定；自动验收不依赖它们。
3. v1.5 relationship note、Edge Evidence line 和 Provider token 再校验缺口，是在 Agent wrapper 中补齐还是先以 v1.5 patch 修复，必须避免同时改变 Retrieval 排序。
4. 本地单进程 Coordinator 是否满足首版部署；启用多个 FastAPI worker 前必须先用两个 Coordinator Lease 测试证明不会双执行。多主/PostgreSQL 不属于 v1.6 范围。
5. Agent Run DB 与 Checkpoint DB 的备份、恢复和 retention 是否需要同一运维命令；无论实现形式如何，都必须保留两者独立职责和一致性检查。

## 22. Definition of Done

v1.6.0 完成必须同时满足：

1. ResearchState、ResearchPlan、PlanStep、StepOutputRef、ArgumentBinding、PlanStepRuntime、ToolObservation、EvidenceAssessment、AgentBudget、Run/API/错误 Schema 全部严格校验、JSON round-trip，并有版本字段。
2. 后续 Step 只能通过受控 StepOutputRef 使用前序 Observation 的 `entity_ids|chunk_ids|edge_ids|evidence_ids`；不支持 JSONPath、模板、表达式或任意字段。
3. 未来 Step、未知字段、越界 index、required 缺失、literal/binding 重名和错误 cardinality 100% 在 handler 执行前拒绝；resolved arguments 100% 通过目标 Tool Input Schema。
4. State 不保存完整仓库/论文、大量 Chunk、Secret、完整 Prompt、Provider/DB/handler 对象；标准 10-call fixture 的 checkpoint State 有自动体积上限。
5. ResearchRunStore 是 API 状态、Idempotency-Key、cancel、Lease、terminal、Plan history 和 retention 权威源；LangGraph Checkpointer 只负责 Graph State、checkpoint/history、Interrupt 和节点恢复。
6. `research_runs`、`research_run_leases`、`research_plan_versions` 有独立 Agent migration、事务和回滚测试，不修改 v1.4 事实数据库语义；每个验证 Plan version 都可审计。
7. HTTP 202 创建只写 queued Run；所有后台执行由保存 task handle 的 ResearchRunCoordinator 管理，不存在无人管理的裸 `asyncio.create_task()`。
8. 同一 Run 同时最多一个有效 Lease；两个 Coordinator 竞争、heartbeat、Lease 过期重领和 Lease 丢失后的迟到结果丢弃均有自动测试。
9. 服务启动能领取 queued 和 Lease 过期且 checkpoint 可恢复的 Run；graceful shutdown 停止新领取、有限等待节点并使未完成 Run 保持可恢复，不误记业务 failed。
10. Run 状态固定为计划中的非终态和四个终态；任一非终态取消必须经过 `cancelling → cancelled`；terminal transition 原子、幂等且不可逆。
11. `partial` 是不可 Resume 终态；Resume 只允许 `paused|interrupted`。继续 partial 必须创建带 `parent_run_id/continued_from_run_id/seed_evidence_ids` 的新 Run。
12. Direct → Planned 最多一次且不增加 `replan_count`；Replan 只统计已有验证 Plan 被新验证 Plan 替换。
13. PlanStepRuntime 准确表示 `pending|resolving|running|success|empty|failed|skipped`；证据充分后剩余 Step 标记 skipped，Replan 后旧 runtime 历史仍可查询。
14. `step_execution_id` 用于 Plan 审计，semantic `tool_call_key` 使用 run/repo/version/tool/canonical resolved arguments；相同成功调用可跨 Replan 复用。
15. 参数变化或 repo/version 变化产生新 tool key；failed/timeout 默认不复用；成功 reuse 不增加 `tool_call_count`，只增加 `tool_reuse_count`。
16. 8 个工具均有正常、empty、非法参数、timeout/late result 和 Mock 测试；所有返回 ID 与固定 repo/version 一致，跨版本泄漏和 forbidden tool call 均为 0。
17. Tool Handler 优先 async；同步任务使用有界线程池。Timeout/Cancel/Lease 丢失后的迟到结果不能写 Observation、State 或 Run View，未结束线程任务不超过配置上限。
18. Executor 一次只执行一个 Step，第一版无并行 DAG；`MAX_PLAN_STEPS=6`、`MAX_TOOL_CALLS=10`、`MAX_REPLAN_COUNT=2`、`MAX_TOOL_FAILURES=3`、`MAX_GRAPH_HOPS=2`、每次最多30结果和最终8 ContextItem在所有路径不可越过。
19. Replan 只由 allowlist reason 触发；相同失败参数或无实质变化的计划不得再次执行；预算耗尽稳定进入不可恢复 Partial。
20. Query Type 最低证据规则均有正/负例；Locked Evidence Sufficiency Accuracy 不低于 90%，证据不足不得返回 completed。
21. Answer 顺序固定为 build context → draft generation → Citation Validation → Claim Verification → deterministic Finalizer；ClaimVerifier 永远不接收未经验证的 citation。
22. Citation Validity 为 100%；非法 ID 和模型改写 line/page 被拒绝。Unsupported 确定性结论不留在最终可见正文，partial support 必须限定表达，全无支持时为 evidence-only partial。
23. Context 在 Provider 调用前执行实际限制再校验；超限时按 rank 确定性删除，Evidence ID/路径/行号不被静默截断。
24. 依赖安全下限为 `langgraph>=1.0.10` 与 `langgraph-checkpoint-sqlite>=3.0.1`，兼容 spike 后固定精确版本或已验证安全范围；低于下限不能安装。
25. Checkpoint strict msgpack allowlist 实际应用并有测试；未批准类型、用户控制 metadata key、Saver 不支持 allowlist 或不兼容类型均 fail closed，不能只检查环境变量。
26. 节点完成先写 checkpoint 再 CAS Run Store；Run 更新失败可从 checkpoint 幂等 repair。Run 声称可恢复但 checkpoint 缺失时返回 `checkpoint_unavailable`，不得从 START 重放。
27. Idempotency-Key 只存 hash并按 caller scope 隔离；同 key+同 request 返回原 Run，同 key+不同 request 固定 HTTP 409 `idempotency_key_conflict`，无 key 每次新建 Run。
28. 4 个 Agent API 路由始终注册；flag 关闭稳定返回 503。Create/status/resume/cancel、terminal、Lease、Coordinator 和 Run/checkpoint consistency 有 OpenAPI/API 集成测试。
29. 30 条 Agent Benchmark（20 Dev + 10 Locked）报告 Task Success、Required Evidence Coverage、Forbidden Tool Call Rate、Budget Compliance、Citation Validity、Terminal Correctness、Route/Plan/Tool diagnostics、Direct Escalation、Replan、Reuse、Recovery、延迟和 Token；主要结论不依赖唯一工具顺序或 LLM Judge。
30. Locked Test Task Success Rate 不低于 80%，Required Evidence Coverage 不低于 90%，Forbidden Tool Call Rate 为 0，Budget Compliance 和 Citation Validity 为 100%，Terminal State Correctness 不低于 90%，可恢复故障 Recovery Rate 不低于 80%。
31. Research Agent Graph 独立于现有 Analysis Graph；未修改离线节点顺序、v1.4 事实、v1.5 Retrieval 排序或旧 API 行为。
32. 自动测试不调用真实模型、不下载资源、不访问网络；真实 Provider 实验单独记录 consent、model revision、预算、fallback 和费用。
33. 完整 `python -m pytest -q`、前端测试、前端 build 和 `scripts/validate.sh` 全部通过，真实结果写入 v1.6 验收文档。
34. v1.4/v1.5 Entity、Edge、Chunk、Evidence ID，旧 JSON、报告、Retrieval API、固定 Research Query API 和前端保持 Schema 与规范化语义兼容。

本文件只定义后续实施方案。本轮没有实现 Planner、Executor、ToolNode、动态 LangGraph、Checkpointer、Agent API 或任何正式 Agent 功能代码。
