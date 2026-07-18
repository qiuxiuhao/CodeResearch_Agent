# v1.6.0 动态 Research Agent

v1.6 新增独立 `ResearchState` 和独立 LangGraph。它只调用 v1.5 的只读 Retrieval/Index
Service，不插入或重构现有离线 Analysis Graph，也不允许 Shell、Python 执行、任意文件读取
或仓库写入。

## 安装与开关

```bash
pip install -e '.[agent]'
export RETRIEVAL_ENABLED=true
export RESEARCH_AGENT_ENABLED=true
```

安全下限为 `langgraph>=1.0.10` 和 `langgraph-checkpoint-sqlite>=3.0.1`。Checkpoint
serializer 显式禁用 pickle fallback，并只允许 ResearchState 所需的项目 Pydantic 类型。

可配置路径：

```text
STRUCTURED_INDEX_DB_PATH=data/structured_index.sqlite3
RESEARCH_RUN_DB_PATH=data/research_runs.sqlite3
RESEARCH_CHECKPOINT_DB_PATH=data/research_checkpoints.sqlite3
RESEARCH_AGENT_MAX_CONCURRENT_RUNS=2
RESEARCH_AGENT_SYNC_TOOL_CAPACITY=4
```

`ResearchRunStore` 是 API 状态、Idempotency-Key hash、cancel flag、lease、Plan 历史和终态
的业务权威源；SQLite Checkpointer 只保存图状态和节点恢复信息。Coordinator 由 FastAPI
lifespan 管理，启动时领取 queued/lease-expired Run，关闭时停止领取并把未完成任务保留为
可恢复的 `interrupted`，不会启动无人管理的裸后台任务。

## 固定边界

- Route 使用规则式特征；简单问题 Direct Retrieval，复杂问题进入 Structured Planner。
- Planner 只能选择八个注册工具；Provider 未授权、不可用或输出非法时使用确定性计划。
- Step 输出只能通过 `StepOutputRef` 引用更早步骤公开的 entity/chunk/edge/evidence IDs。
- 相同 Run/repository/index/tool/解析后参数的成功调用可跨 Replan 复用；失败默认不复用。
- 顺序为 Context → Draft Answer → Citation Validation → Claim Verification → Finalizer。
- 非法引用被删除；unsupported claim 不会作为确定性结论保留在可见答案中。
- `partial` 是终态；只允许 `paused|interrupted` 恢复。

默认预算：六个 Plan Step、十次实际工具调用、两次 Replan、三次工具失败、Graph 两跳、
每次最多 30 个检索结果和最终八个 ContextItem。预算用尽时返回带真实 Evidence 的 partial
结果。

## API

```text
POST /repositories/{repo_id}/research/agent/runs
GET  /research/agent/runs/{run_id}
POST /research/agent/runs/{run_id}/resume
POST /research/agent/runs/{run_id}/cancel
```

创建接口返回 HTTP 202。建议传递 `Idempotency-Key`；同一 caller scope、同 key 和同请求返回
原 Run，同 key 不同请求返回 HTTP 409 `idempotency_key_conflict`。未提供 key 时每次创建新
Run。Feature Flag 关闭时路由仍存在并稳定返回 HTTP 503 `research_agent_disabled`。

Cancel 先把 Run Store 置为 `cancelling`；各节点入口与工具返回后读取实时 cancel flag，最后
进入 `cancelled`。Resume 固定原 repository/index version，并要求兼容的 graph/state version
及存在的 checkpoint。

## 评测

`evaluation/agent/benchmark_v1.jsonl` 固定 30 条：10 条 Direct、15 条 Planned 和 5 条
证据不足/失败问题，其中 10 条为 locked test。主要指标是 Task Success、Required Evidence
Coverage、Forbidden Tool Call Rate、Budget Compliance、Citation Validity 和 Terminal State
Correctness；工具顺序只作为诊断，不要求唯一执行路径。

离线评测已有结果文件时运行：

```bash
python scripts/evaluate_agent.py evaluation/agent/outcomes.jsonl
```

自动测试只使用 Mock/Fake 工具和本地 SQLite，不调用真实 Provider、不下载模型。
