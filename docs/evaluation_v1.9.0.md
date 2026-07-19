# v1.9 Evaluation、Bad Case 与 Regression Loop

v1.9 在业务 Store、Checkpoint 与 Trace 之外增加独立评测控制面。Evaluation 读取版本化业务
Artifact 或隔离 Fixture，生成不可变 CaseResult/MetricResult；它不修改 Gold、不覆盖原 Run，也不把
Trace 当作事实标签。

`EvaluationGraph` 是独立于 `IndexBuildGraph` 与 `ResearchAgentGraph` 的编排边界；Coordinator
只通过该入口驱动 Dataset、Adapter、Metric、Comparison、Gate 与 Bad Case 流程，不把 Evaluation
状态写入 `ResearchState` 或业务 Checkpoint。

## 核心边界

```text
EvaluationSubject = 被评测的 Commit + Config + Prompt + Model + Dependency Lock
EvaluationRun     = 一次不可变执行
BaselineBinding   = 某 Dataset/Component/Mode 当前采用的 completed Run
Business Store    = 业务事实与运行状态权威
Trace Store       = best-effort 诊断数据，不是 Gold
```

正式 Baseline Subject 必须引用干净的完整 Commit SHA；Tag 只是可读标签。未提交 Patch 可用于开发
实验，但不能晋升正式 Baseline。Dataset Version 冻结后不可原地更新；Gold、Fixture 或 Case 变化均
创建新版本。

## Dataset 与 Adapter

Split 为 `dev|locked_test|regression`，来源为
`human_authored|confirmed_bad_case|synthetic_fixture`。六个严格判别联合覆盖：

- Index：Entity、Edge、Evidence、Chunk、Manifest 与 ID 稳定性。
- Retrieval：Entity/Chunk relevance、Graph path、fallback 与排序。
- Agent：Route、Plan、Tool、Evidence、Budget、Recovery 与终态。
- Alignment：Profile、逐 Selection relation、Evidence、Abstention 与 Candidate probability。
- Answer：Answer point、Claim、Citation 与 Evidence-only 约束。
- Observability：Operation tree、Link、Redaction、Completeness、Drop 与开销。

Index Adapter 把 reference index 当 Gold fixture，在临时 DB/隔离 namespace 构建 candidate index；它
不得切换生产 active version。其他 Adapter 也固定 Fixture 中的 repo/index/paper，不追随生产 active。

## 执行模式

- `offline_recompute`：只读取已持久化 Artifact 重算指标，不调用模型。
- `deterministic_fixture`：Fake/Mock + 固定 seed，供 CI 使用；不访问网络或业务 Store。
- `live_experiment`：默认关闭，要求 `EVALUATION_LIVE_ENABLED=true`、local-admin 权限、显式 consent、
  Provider budget 和 Trial/Repeat。每次 repeat 使用独立 Evaluation Run 与 Trace。

Live 结果记录 Provider/model/revision/temperature/seed。单个 Trial 不能成为正式 Baseline；Gate Config
规定最小完成 repeat 数。Live Replay 创建新 run/trace，不覆盖原结果且不写回 Gold。

## Metric、Comparison 与 Gate

MetricDefinition 版本化。当前 Engine 输出 Retrieval Recall/MRR/nDCG/Graph Path/Fallback、Agent
route/tool/evidence/budget、Alignment Candidate Recall/Pair F1/Exact Set/Selective/Coverage/Brier/ECE、
Answer coverage/support/citation，以及 Trace completeness/integrity/redaction/drop 等指标。

Comparison 保存共同 Case、排除 Case和不可比 Metric。Quality 可以在严格共同 Case 范围内展示；
Performance 只有 environment/cache/concurrency/hardware hash兼容时才能 Gate。`incompatible` Comparison
不会自动 Gate。

Gate Config 分 `ci|release|manual`：

- CI：Hard invariant + 小型 deterministic regression，不要求真实 Provider。
- Release：完整 human-authored/Locked Dataset、关键 subgroup、性能与必要 Live repeats。
- Rule 固定 threshold、min sample、incomplete policy 与 warning/block；运行后不得补挑 subgroup。

## Bad Case 与 Promotion

Bad Case fingerprint 使用 stable case family、component、symptom 与规范 failure code；相同失败追加
Occurrence，Root Cause 建议版本变化不会产生新 Case。状态机为：

```text
open → triaged → confirmed → fixing → fixed → verified → closed
open/triaged/confirmed/fixing → rejected
closed → open  # recurrence event
```

`fixed` 必须有 code/config/prompt/model/dataset FixReference；`verified` 必须由匹配的、预修复已稳定
复现的 Regression Case、新评测 CaseResult 和相关 Hard Rule共同证明。与该 Case 无关的其他失败不阻止
case-level verification。

Promotion 顺序为 confirmed → 新 Draft Dataset Version/Regression Case → 预修复复现 → Fix → 新 Subject
评测 → verified。旧 Frozen Dataset 不被修改。

## Store、Coordinator 与权限

默认数据库为 `data/evaluation.sqlite3`，migration 为
`backend/app/persistence/evaluation_migrations/001_evaluation.sql`。Store 使用 WAL、foreign keys、短事务、
Run Lease、Idempotency-Key hash、Cancel/Retry 与 active Baseline 部分唯一索引。它不修改 structured index、
Research/Alignment Store、Checkpoint 或 Trace DB。

Evaluation API默认关闭，当前认证系统不足时只允许本机管理员。caller scope hash只做关联，不能授权。
主要接口：

```text
POST /evaluations/runs
GET  /evaluations/runs
GET  /evaluations/runs/{run_id}
POST /evaluations/runs/{run_id}/cancel
GET  /evaluations/runs/{run_id}/results
GET  /evaluations/runs/{run_id}/metrics
POST/GET /evaluations/comparisons
POST/GET /evaluations/baselines
GET  /evaluation/datasets
GET  /evaluation/datasets/{dataset_id}
GET/POST /bad-cases/...
```

Coordinator 限制 Run/Case/Provider并发，通过 SQLite Lease恢复过期 Run，并在 graceful shutdown 后允许
重新领取。Evaluation 创建独立 `evaluation` Trace；202 API以 `queued_from` Link关联。Replay/原业务 Trace
只用 Link/ArtifactRef引用。

## Alignment Gold 状态

真实六对 repo-paper、72 正例 + 20 hard negative 的双人 Gold 尚未提供，状态固定为
`ALIGNMENT_BENCHMARK_PENDING`。v1.9 不会用 Legacy、Scorer、LLM 或 Trace 指标伪造 Gold。检查命令：

```bash
python scripts/validate_alignment_gold.py evaluation/alignment/benchmark_v1.jsonl --release
```

synthetic regression suite只验证 Schema、Adapter、Metric与Gate合同，不能产生 Alignment质量结论。
