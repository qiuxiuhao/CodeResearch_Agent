# CodeResearch Agent v1.6.0 基线验收记录

状态：v1.7.0 开工前冻结

验收日期：2026-07-18

Git 基线：`c6c3337f12935cb5251a966e8ca673366f5e8cc2`（tag `v1.6.0`，`feat: complete dynamic research agent v1.6.0`）

## 1. 事实口径与工作区

本记录基于已提交并打 tag 的 v1.6.0 实现、实际代码审查和在该实现上执行的完整验收。`v1.6.0` tag 固定指向上述完整 Commit SHA；后续 v1.7 不得把其他工作树状态冒充为该基线。

## 2. Git 与运行环境

| 项目 | 实际值 |
| -- | -- |
| 分支 | `upgrade/v1.6-dynamic-research-agent` |
| v1.6 Commit | `c6c3337f12935cb5251a966e8ca673366f5e8cc2` |
| Git tag | `v1.6.0` |
| `backend.app.main.app.version` | `1.6.0` |
| `pyproject.toml` 版本 | `1.6.0` |
| 已安装 distribution `code-research-agent` | `0.6.0`，与工作树版本不同步 |
| Conda 环境 | `code-research-agent` |
| Python | `3.11.15` |
| Node.js | `v24.15.0` |
| SQLite | `3.53.3` |
| LangGraph | `1.2.8` |
| langgraph-checkpoint | `4.1.1` |
| langgraph-checkpoint-sqlite | `3.1.0` |
| Pydantic | `2.13.4` |
| FastAPI | `0.139.0` |
| qdrant-client / fastembed | 未安装 |

`pyproject.toml` 要求 `langgraph>=1.0.10,<2.0`，并在 `dev` 和 `agent` extra 中要求 `langgraph-checkpoint-sqlite>=3.1.0,<3.2.0`。当前环境满足该范围。

## 3. 完整验收结果

### 3.1 独立命令

| 命令 | 结果 | 实际摘要 |
| -- | -- | -- |
| `python -m pytest -q` | 通过 | `312 passed, 6 warnings in 53.22s` |
| `npm --prefix frontend test` | 通过 | 16 个测试文件、29 个测试通过，1.53s |
| `npm --prefix frontend run build` | 通过 | TypeScript、Vite 和 build contract 通过；3695 modules，2.95s |
| `bash scripts/validate.sh` | 通过 | 后端 `312 passed, 6 warnings in 53.04s`；前端 29 passed；构建通过；`Validation completed.` |

Python 命令通过 `code-research-agent` Conda 环境执行。`validate.sh` 的前端依赖步骤成功安装 272 个包。

### 3.2 已知警告

- Starlette/FastAPI `TestClient` 提示当前 httpx 接法已弃用并建议迁移到 httpx2。
- PyMuPDF/SWIG 类型产生 `__module__` 相关 DeprecationWarning。
- `npm ci` 报告 `whatwg-encoding@3.1.1` 已弃用。
- Vite 报告部分 Mermaid 相关 chunk 压缩后超过 500 kB。

以上均未导致验收失败，本轮未修复。

## 4. v1.6 Research Agent 实际组成

### 4.1 独立 State 与 Schema

`backend/app/agents/research/state.py::ResearchState` 是独立于离线 `AgentState` 的 `TypedDict`。实际字段分为：

- 身份与版本：`state_schema_version`、`graph_version`、`run_id`、`thread_id`、`parent_run_id`、`continued_from_run_id`、`repo_id`、`index_version_id`。
- 查询与路由：`query`、`query_type`、`route`、`route_reason`、`direct_escalated_to_planned`。
- 计划与步骤：`plan`、`pending_plan`、`plan_history_ids`、`current_step_index`、`step_runtime`、`resolved_arguments`、`step_resolution_failed`。
- 观察与证据：`observations`、`evidence_ids`、`seed_evidence_ids`、`entity_ids`、`evidence_assessment`、`evidence_sufficient`、`missing_evidence`。
- 回答：`context`、`draft_answer`、`validated_answer`、`answer`、`confidence`、`answer_enabled`、`external_text_consent`。
- 预算与运行：`tool_call_count`、`tool_reuse_count`、`replan_count`、`tool_failure_count`、`token_usage`、`status`、`previous_status`、`stop_reason`、`errors`、`cancel_requested`、`resume_count`、`last_resumed_at`、时间戳。

State 不保存仓库全集、完整论文、Secret、Provider、数据库连接、工具 handler 或任意 callable。

`backend/app/agents/research/schemas.py` 实际实现严格 Pydantic 模型，包括 `StepOutputRef`、`ArgumentBinding`、`PlanStep`、`ResearchPlan`、`PlanStepRuntime`、`ToolObservation`、`EvidenceAssessment`、Draft/Validated/Final Answer 和 API Run View。

### 4.2 Router、Planner、参数绑定与 Executor

- `RuleBasedResearchRouter` 复用 v1.5 `RuleBasedQueryProfiler`，将 call chain、architecture、training、inference、paper alignment、general repository 及复杂关键词路由到 planned；其他单证据目标走 direct。
- `StructuredPlanner` 只有在 `external_text_consent=true` 且 Provider 可用时调用 `ModelRouter.generate_structured()`；否则使用 `RuleBasedPlanner`。Provider 输出仍经过 Pydantic 和 `PlanValidator`。
- `PlanValidator` 拒绝未知工具、非连续 ordinal、未来步骤引用、未知输出字段、非依赖绑定、参数 cardinality 错误和非法 literal。
- `StepArgumentResolver` 只允许绑定前序 Observation 的 `entity_ids|chunk_ids|edge_ids|evidence_ids`，解析后再次通过工具 Input Model。
- `ResearchExecutor` 使用 `run_id + repo_id + index_version_id + tool_name + canonical arguments` 生成语义工具调用键；成功结果可跨 Replan 复用，复用不增加实际调用数。
- `AgentBudgetLimits` 实际上限为 6 个 Plan Step、10 次 Tool Call、2 次 Replan、3 次 Tool Failure、2 hop、每次最多 30 个检索结果和最终最多 8 个 ContextItem。

### 4.3 Tool Registry

`backend/app/agents/research/tools/default_tools.py::build_default_tool_registry()` 注册 8 个只读工具：

| 工具 | 实际复用能力 | 超时 / 最大结果 |
| -- | -- | -- |
| `search_hybrid` | `RetrievalService.search` | 8s / 30 |
| `get_symbol_source` | `RetrievalReadStore.list_documents` 与 Evidence 查询 | 3s / 1 |
| `get_graph_neighbors` | 同 repo/version 的 Edge 查询 | 3s / 30 |
| `get_call_path` | CALLS/INSTANTIATES 最多 2 hop BFS | 4s / 5 path |
| `get_model_flow` | 图邻居的模型关系子集 | 4s / 30 |
| `search_paper` | paper-only Hybrid Retrieval | 8s / 20 |
| `get_alignment` | 读取 `ALIGNS_WITH` 入/出边 | 3s / 20 |
| `inspect_config` | config filter 的 Hybrid Retrieval | 3s / 10 |

所有工具的 `repo_id + index_version_id` 均由服务端 `ToolExecutionContext` 注入。异步超时使用 `asyncio.timeout()`；同步 SQLite/CPU 工作进入容量默认 4 的受控线程池，超时后的迟到结果不能写回当前 Observation。

### 4.4 Evidence、回答与验证顺序

`EvidenceSufficiencyChecker` 根据 Query Type 检查实体/Evidence、Graph Edge，以及 paper alignment 的 paper/alignment 结果；Direct 证据不足时仅允许一次升级到 Planned，且不增加 `replan_count`。

实际回答顺序为：

```text
build_context
→ generate_answer
→ validate_citations
→ verify_claims
→ finalize_answer
```

`AgentCitationValidator` 先校验 citation 的 context/evidence/entity，并用 Context 中事实覆盖 path、line、page；`ClaimVerifier` 当前只以“是否仍有合法 citation”判定 supported/unsupported，不进行更深的语义蕴含验证；`AnswerFinalizer` 从可见正文删除 unsupported 确定性结论，全部无支持时返回 evidence-only partial。

## 5. ResearchRunStore、Checkpointer 与 Coordinator

### 5.1 职责分工

- `ResearchRunStore` 是业务控制面权威源：Run/API 状态、caller scope、Idempotency-Key hash、cancel flag、lease、terminal transition、plan version、retention metadata。
- `ResearchCheckpointRuntime` 是 Graph 执行状态源：`ResearchState` checkpoint、节点恢复、thread history。
- `ResearchRunCoordinator` 由 FastAPI lifespan 启停，持有受控任务句柄、轮询 queued/过期 lease run、原子领取和续租、执行 `graph.astream()`、发布状态、处理重启恢复和 graceful shutdown。

### 5.2 实际数据库

默认路径：

- `data/research_runs.sqlite3`：业务 Run Store。
- `data/research_checkpoints.sqlite3`：LangGraph SQLite Checkpoint。

Research Run migration `001_research_runs.sql` 设置 `PRAGMA user_version=1`，创建：

- `research_runs`
- `research_run_leases`
- `research_plan_versions`

当前项目 `data/` 中尚不存在上述两个运行库；只存在旧函数知识库和 LLM/Image cache。自动测试使用临时目录，所以本轮未把持久化生产数据量记为已验证事实。

### 5.3 状态与恢复

持久状态包括：

```text
queued → routing/planning/retrieving/executing/assessing/replanning
       → building_context/generating/validating/verifying/finalizing
       → completed|partial|failed

任一非终态 → cancelling → cancelled
paused|interrupted → resume 后继续 checkpoint
```

`completed|partial|failed|cancelled` 为终态；`partial` 不可 resume。Resume 仅允许 `paused|interrupted`，验证 graph/state version 和 checkpoint，增加 `resume_count`。应用关闭未完成的任务被标记 `interrupted`，而不是业务失败。

Checkpoint 启动时强制 LangGraph `>=1.0.10`、SQLite Checkpointer `>=3.0.1`；实际配置关闭 pickle fallback，并显式 allowlist 项目 State 所需 Pydantic 类型。

## 6. LangGraph 与 API

### 6.1 Graph

`backend/app/agents/research/graph.py::build_research_agent_graph()` 创建独立动态 Research Agent Graph，不修改 `backend/app/agents/graph.py` 的离线 Analysis Graph。主路径实际包含：

```text
route_query
├─ direct_retrieve → assess_evidence
└─ create_plan → validate_plan → resolve_step_arguments
   → mark_step_running → execute_step → assess_evidence

assess_evidence
├─ build_context
├─ 下一 Step
├─ Direct → Planned 升级
├─ replan
└─ finish_partial

build_context → generate_answer → validate_citations
→ verify_claims → finalize_answer
```

取消在节点入口和工具返回后检查 Run Store 的 `cancel_requested`。

### 6.2 API 与 Feature Flag

四个路由始终注册：

- `POST /repositories/{repo_id}/research/agent/runs`
- `GET /research/agent/runs/{run_id}`
- `POST /research/agent/runs/{run_id}/resume`
- `POST /research/agent/runs/{run_id}/cancel`

`RESEARCH_AGENT_ENABLED=false` 为默认值；关闭时返回 HTTP 503 `research_agent_disabled`。创建 Run 返回 HTTP 202，由 Coordinator 异步执行。

Idempotency 规则实际为同 caller scope + 同 Key + 同 request hash 返回原 Run；同 Key 不同请求返回 HTTP 409 `idempotency_key_conflict`。数据库只保存 Key hash。当前 caller scope 来源为 `X-Caller-Scope`，否则退化为客户端地址；这不是完整身份认证系统。

## 7. Agent Benchmark 与真实指标

`evaluation/agent/benchmark_v1.jsonl` 实际包含 30 条：

- Dev：20 条。
- Locked Test：10 条。
- 题目结构：10 条 Direct、15 条 Planned、5 条 evidence insufficient/failure。

`AgentBenchmarkCase` 实际包含 required/optional/forbidden tools、required Evidence/Edge、最大 Tool Call、期望 route/sufficiency/terminal state 和 fault injection。`evaluate_agent_benchmark()` 可计算 Task Success、Route Accuracy、Evidence Coverage、Forbidden Tool Rate、Citation Validity、Terminal Accuracy、Tool/Plan/Argument 指标、Replan/Recovery/Budget、延迟和 Token。

本工作树没有版本化的 30 条真实 `AgentBenchmarkOutcome` 结果文件；`scripts/evaluate_agent.py` 需要外部 outcomes JSONL 才能运行。因此本基线不能真实报告 Task Success、MRR 类效果、Agent 平均延迟、fallback/recovery 或 Token 数值。现有 312 个测试证明合同和确定性行为，不等价于 30-case 端到端质量评测。此项是 v1.6 的验收缺口，不能填入推测值。

## 8. 当前论文代码对齐对 v1.6 的输入

`get_alignment` 当前只查询 v1.4 结构化索引中的 Legacy `ALIGNS_WITH` Edge：输入一个 `entity_id`，调用 `graph_neighbors()` 读取同一 repo/version 的入边和出边，并返回 entity/edge/evidence ID 与文本摘要。它不运行新的对齐算法、不读取独立对齐决策库，也不区分 reviewed、accepted、abstained 或 needs_review provenance。

`paper_alignment` Query Profile 使用 Dense 1.2、Sparse 0.8、Graph 1.5 权重，最多 2 hop，允许 `ALIGNS_WITH|CONTAINS|DEFINES`，Hybrid/Reranker 融合权重为 0.4/0.6（Reranker 启用时）。真实 Dense/Reranker 依赖未安装，因此这里只验证了代码合同和 Fake 路径。

## 9. 已知问题与 v1.7 必须保持的能力

### 9.1 已知问题

1. HEAD 仍是 v1.5.0，v1.6 实现未提交；安装 distribution 版本仍为 0.6.0。
2. 没有 30-case 真实 Agent outcome/指标报告，只有 Schema、评测器和自动测试。
3. 当前 Claim Verifier 只检查合法 citation 的存在，不验证 Claim 与证据的语义蕴含程度。
4. 当前 caller scope header/客户端地址仅是本地隔离机制，不是生产级身份认证。
5. Coordinator 是本地单进程 asyncio + SQLite lease 方案，未验证多实例生产部署。
6. 当前环境没有 Qdrant/FastEmbed 或真实 Embedding/Reranker，paper alignment Retrieval 的真实模型质量未验收。
7. `get_alignment` 只读取 Legacy Edge，不包含独立对齐版本、候选分数、abstention、review 或 provenance。
8. 项目 `data/` 当前没有持久 Research Run/Checkpoint 运行样本，恢复测试均使用临时数据库。

### 9.2 v1.7 必须保持

- 不修改 v1.4 CodeEntity/PaperEntity/KnowledgeEdge/EvidenceRef/SymbolChunk ID 与事实语义。
- Legacy `paper_code_alignment.json`、报告和 `ALIGNS_WITH` Edge 继续可读，不被新派生决策覆盖。
- v1.5 Retrieval 的 Preliminary RRF、Graph Expansion、Final RRF、Reranker 排序保持不变。
- v1.6 Agent Graph、Planner、Executor、State、Run Store 和 API 主逻辑保持不变；仅通过 `get_alignment` 的 Service 边界增量接入。
- 每次查询和对齐运行固定 `repo_id + index_version_id + paper/index version`，不得跨版本混合。
- 新对齐结果必须保留 paper/code Evidence、来源、模型/配置版本和人工审核 provenance。
- LLM 只能验证已有候选，不能生成不存在的实体、路径、行号或事实 Edge。
- 自动测试不访问网络、不下载模型、不调用真实付费 Provider。
- 旧分析 API、旧报告、前端和离线 Analysis Graph保持 Schema 与规范化语义兼容。
