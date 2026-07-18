# CodeResearch Agent v1.7.0 基线

验收日期：2026-07-18
用途：v1.8.0 统一 Trace 与可观测性设计的事实基线

## 1. 基线身份

| 项目 | 实际值 |
| -- | -- |
| Branch | `upgrade/v1.7-paper-code-alignment` |
| Commit | `25edd020e533baa90bee432f4a6251fc0fac531b` (`feat: implement paper-code alignment v1.7.0`) |
| Tag | HEAD 无 tag；不能将其描述为已发布的 `v1.7.0` tag |
| 工作区 | 验收开始时 `git status --short` 为空 |
| Shell Python | 3.13.13，路径所属环境没有安装 pytest |
| 项目验证环境 | Conda `code-research-agent`，Python 3.11.15 |
| Node.js | v24.15.0 |
| 项目版本 | `pyproject.toml` 与 FastAPI app 均为 1.7.0 |

已核对的关键依赖版本：FastAPI 0.139.0、Pydantic 2.13.4、httpx 0.28.1、LangGraph 1.2.8、`langgraph-checkpoint` 4.1.1、`langgraph-checkpoint-sqlite` 3.1.0。当前环境未安装 Qdrant/FastEmbed 可选依赖。

前端关键版本：React 19.2.7、TypeScript 5.9.3、Vite 7.3.6、Vitest 3.2.7、Mermaid 11.16.0。

## 2. 验收命令与结果

| 命令 | 结果 |
| -- | -- |
| `python -m pytest -q` | 失败：当前 shell Python 3.13.13 没有 pytest；这是环境选择问题，不是测试失败 |
| `npm --prefix frontend test` | 通过：16 个测试文件、29 个测试 |
| `npm --prefix frontend run build` | 通过：3695 modules；存在既有大 chunk warning |
| `bash scripts/validate.sh` | 通过；脚本切换到 Conda `code-research-agent` 后执行完整验证 |

`scripts/validate.sh` 的实际结果：

- 后端：343 passed，6 warnings，53.62s。
- 前端：16 个测试文件、29 个测试通过。
- 前端 build：通过，3695 modules。
- 最终输出：`Validation completed.`

Warnings 为 FastAPI/Starlette TestClient 的 httpx 弃用提示、SWIG/PyMuPDF 弃用提示、`whatwg-encoding` npm 弃用提示和 Vite/Mermaid chunk size 提示。本轮只记录，不修改代码。

## 3. v1.7 Alignment 实际实现

### 3.1 Schema 与 Profile

`backend/app/alignment/schemas.py` 已实现严格 Pydantic v2 模型，包括：

- `PaperModuleProfile`：显式 `profile_type`、`granularity`、`source_group_key`、父 Profile、Evidence、质量和缺失字段。
- `AlignmentCandidate`、`AlignmentFeatureVector`、`AlignmentCandidateScore`。
- `AlignmentSelection`、`AlignmentDecision`、`AlignmentVerification`。
- `AlignmentReview`、`EffectiveAlignmentDecision`。
- `AlignmentRun`、`AlignmentModelProfile`、`AlignmentDeployment`。

`paper_module_extractor.py` 从现有论文分析、PaperEntity 和 Figure Evidence 形成规则优先的 Profile；Profile ID 和 extractor generation 被版本化。正文、Figure、Formula、Training/Inference、Configuration 的粒度由显式类型表达。结构化模型增强仍受 Evidence catalog 和 Schema 约束。

### 3.2 Candidate、Feature、Scorer 与 Calibration

`candidate_generator.py` 与 `candidate_merger.py` 实现 exact/alias、Sparse、Dense、role、Code Graph、Figure topology 和 Legacy 多路候选合并，并固定 repo/index version。候选保留 source、rank、贡献和 Evidence；Dense 缺失可以降级。

`feature_extractor.py` 输出 name、semantic、role、structure、IO、shape、formula/variable、Figure topology 和 evidence quality 等版本化特征，区分 missing 与 not-applicable。

`scorer.py`、`calibrator.py` 与 `set_builder.py` 将 Candidate 原始分、coverage penalty、Candidate-level probability 和 Profile-level set decision 分开。多目标使用逐项 `AlignmentSelection`，关系类型不再由整个 Decision 共用。低分或模型缺失默认 abstain，不自动推导 no implementation。

代码具备 pair-level calibration/evaluation 结构，但当前仓库没有可用于报告真实质量的完整人工 gold 数据。

### 3.3 Verifier

`verifier.py` 只允许 Provider 从传入 Top-K Candidate 中提出 Selection，并验证 Candidate、relation 和 Evidence membership。Provider 不可用、无 consent、超时或输出非法时回退 Scorer。Token metadata 在 Provider 返回时可记录；Verifier 不写 v1.4 事实库。

### 3.4 Store、Coordinator、Lease 与 Cancel

`backend/app/persistence/alignment_store.py` 与独立 migration 管理 `data/paper_code_alignment.sqlite3`。实际对象覆盖 Run、Lease、Model Profile、Deployment、Profile、Candidate、Feature、Score、Decision、Selection、Verification 和 append-only Review。

Store 支持：

- queued 至 active/superseded/failed/cancelled 状态。
- 分阶段短事务和 stage manifest。
- attempt/retry 链、成功结果复用和失败隔离。
- repo/index/paper/model profile 隔离。
- Deployment 指向明确 active Run。
- Review effective revision 与乐观并发控制。

`backend/app/services/alignment_run_coordinator.py` 使用受控 asyncio task、SQLite Lease 和 heartbeat 领取 202 Run，支持启动恢复、过期 Lease 重新领取、Cancel 检查和 graceful shutdown；没有使用无人管理的裸后台任务作为控制面。

### 3.5 API 与 Research Agent 接入

Alignment API 已提供 Run 创建/查询/取消、Alignment 列表与详情、Review、pending Review 和 Deployment 操作。路由始终注册，Feature Flag 关闭时返回结构化 503。API 固定 repo/index/paper/model profile，并实现 caller scope 与 Idempotency-Key 语义。

v1.6 `get_alignment` 通过聚合只读 Service 消费 Legacy 与 v1.7 Deployment 结果，保留 provenance、authority level 和 evidence role。`needs_review` 仅为 hypothesis，不能替代代码或论文事实。Planner、Executor 和 Research Graph 主流程未被改写。

## 4. Benchmark 与实际指标

`evaluation/alignment/benchmark_v1.jsonl` 当前只有一行说明性注释，没有 6 个 repo-paper pair、72 个正例或 20 个 hard negative。因而本基线没有可验证的：

- Candidate Recall@5/10/20、MRR。
- Top-1/Top-3、Micro/Macro F1、Exact Set Match。
- Abstention、Selective Accuracy/Coverage。
- Brier Score、ECE 或 pair-level out-of-fold 指标。
- Locked Test 延迟、fallback 或八组消融结果。

现有单元/集成测试验证的是合同、确定性、隔离和 fallback，不等同于真实对齐质量 Benchmark。v1.8 不得把缺失指标描述成已达成结果。

## 5. 当前可观测能力

### 5.1 已有可复用信号

- API、Analysis、Index、Retrieval、Research Agent 和 Alignment 都已有业务 ID：request/query/task/run/repo/index version 等。
- Retrieval 实际记录 profile、sync、Sparse、Dense、Preliminary RRF、Graph、Final RRF/Reranker 和 total 的阶段延迟。
- Tool Registry/Executor 记录工具 latency、status、error code、semantic tool-call key、reuse 和 result count。
- Provider Runtime 记录 provider/model、attempt、fallback、latency、token、cache/input hash 和 warning。
- Research/Alignment Coordinator 有状态机、Lease、cancel、retry/recovery 边界。
- Structured Index、FTS、Vector、Alignment 均有 generation/run 状态与失败隔离。
- Research Checkpointer 已与 ResearchRunStore 分离。

### 5.2 当前缺口

- FastAPI 只有 CORS middleware；没有 request-ID/trace middleware、统一 Trace Context 或统一异常到 Trace 的映射。
- 新 API 的结构化错误虽然含 `trace_id` 字段，但当前始终为 `None`；旧 Analysis API 仍主要使用原始 `HTTPException(detail=...)`。
- Analysis progress 是进程内状态，只记录节点 start/finish/error 与百分比，没有持久时间线或节点 latency。
- Research 的 `astream` 只在 Coordinator 内消费，没有公开的受控 SSE 事件流。
- 没有统一 Trace/Span/Event Store、Attribute Registry、Redactor、Sampler、Metrics 或 Exporter。
- 没有 Trace Explorer；前端不能显示 Span tree、waterfall、错误、Token/Cost 或 Evidence references。
- 应用日志很少且不统一；没有跨 API、Graph、Tool、Provider、DB 的结构化关联。
- Provider 具 Token 数据但没有稳定的货币成本计算；未知价格时不能推造 cost。

## 6. 已知限制

1. v1.7 HEAD 未打 tag。
2. 直接 shell Python 缺 pytest；完整验证依赖项目指定 Conda 环境。
3. Alignment gold dataset 尚未建立，无法声明真实检索、对齐或校准质量。
4. Qdrant/FastEmbed 可选依赖未安装，真实 Dense/Qdrant 路径未在本环境验收。
5. Caller scope 目前是本地隔离标识，不等同于完整身份认证系统。
6. Analysis progress 为内存态，服务重启后不可恢复。
7. 现有错误结构、日志和 timing 分散，缺少统一 Trace ID。
8. Provider cache 保存业务响应是既有行为；Trace 设计不得复制其完整 payload。

## 7. v1.8 必须保持兼容的能力

- Trace 失败、队列满、Exporter/Store 不可用不得改变任何业务结果、状态机或 API 成功率。
- `ResearchRunStore` 继续作为业务运行控制平面；LangGraph Checkpointer 继续只负责 State/恢复/Interrupt；Trace Store 不替代两者。
- 不把完整 ResearchState、Prompt、Query、源码、论文正文、Checkpoint 或 Provider response 写入 Trace。
- 保留 v1.4 事实 ID/数据库，v1.5 Retrieval 排序与 generation，v1.6 Agent 状态/恢复/预算，v1.7 Alignment Store/Deployment/Review 语义。
- 保留 Analysis progress、现有 API、旧 JSON/报告和前端行为；插桩必须可通过 Noop Recorder 完全关闭。
- repo_id 与 index_version_id 在 Trace Context 中只作关联属性，不能放宽现有版本隔离。
- Token、fallback、cache、Evidence 和 error 只记录受限 metadata/引用；任何内容采集必须显式授权并经过 Redaction。

本文件只记录本轮实际检查到的 v1.7 基线事实，不包含 v1.8 正式功能实现。
