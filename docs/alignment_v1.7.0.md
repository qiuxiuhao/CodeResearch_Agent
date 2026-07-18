# v1.7.0 论文代码对齐 2.0

v1.7 将 Legacy 词项启发式保留为独立召回源，在其上新增 evidence-first 的版本化派生对齐系统。
它不修改 v1.4 事实库、v1.5 Retrieval 排序或 v1.6 Research Agent Graph。

## 固定流程

```text
PaperEntity / Legacy PaperAnalysis / Figure evidence
→ PaperModuleProfile（type、granularity、source_group_key）
→ exact / alias / Sparse / Dense / role / Graph / Figure / Legacy candidates
→ 9 类 Feature + coverage penalty
→ Candidate score + Candidate-level calibration
→ Selection set + Profile decision
→ optional constrained verifier
→ staged SQLite activation
→ explicit deployment / append-only review / Agent read view
```

Decision 支持 `accepted|abstained|needs_review|no_implementation`。低分、空候选、Dense 缺失或
Feature 缺失默认只能 abstain；`no_implementation` 需要强负证据和人工确认。一个 Decision 可有
多个 `AlignmentSelection`，且每个 Candidate 独立保存 relation、概率和 Evidence。

## 隔离和运行

- 事实输入固定 `repo_id + index_version_id + paper_id`。
- 结果另加 `model_profile_id`；所有影响结果的 Profile/Retrieval/Graph/Feature/Calibration/Verifier
  配置进入 `config_hash`。
- HTTP 202 Run 由 lifespan 管理的 `AlignmentRunCoordinator` 执行；SQLite Lease 防止重复执行。
- Profile、Candidate、Feature、Score、Decision 分阶段短事务持久化；默认查询只读 active。
- failed/cancelled 可创建新 attempt；ready/active/superseded 成功结果可幂等复用。
- 默认读取必须通过显式 Deployment，多个 active Model Profile 不会合并。

## Provider 与人工复核

Verifier 只接收 Scorer Top-5 的 Candidate 和受控 Evidence catalog，只能选择已有 Candidate ID、
relation 和 Evidence。请求未授权、Provider 不可用、超时或结果非法时，保留 Scorer decision。

Review 是不可变事件，使用 effective revision 乐观锁。Accept、Reject、Replace、Accept Multiple、
Mark No Implementation 和 Add Note 都只能引用当前 Run 的 Candidate/Evidence；原模型输出永久保留。

## Feature Flag 与 API

```bash
export ALIGNMENT_ENABLED=true
export ALIGNMENT_AGENT_INTEGRATION_ENABLED=true  # 可选
```

默认数据库为 `data/paper_code_alignment.sqlite3`。接口清单见
[API 参考](api_reference.md)，表与状态见[数据库说明](database.md)。

## 评测

```bash
python scripts/evaluate_alignment.py evaluation/alignment/benchmark_v1.jsonl \
  --predictions /path/to/predictions.jsonl \
  --output /path/to/report.json
```

评测器分别输出 Dev/Locked 的 Candidate Recall@5/10/20、MRR、relation-aware F1、Exact Set、
Abstention、Selective Accuracy/Coverage、Evidence precision、Brier/ECE、延迟和 fallback。

真实质量发布门禁需要 6 个固定 repo-paper pair 和 92 条双人标注 Gold。当前仓库只提供严格 Schema、
pair split 校验和 fixture 槽位；未获得论文/仓库授权与人工 Gold 前，评测命令默认以退出码 2 拒绝
把空数据当成发布结果。`--allow-incomplete` 仅用于检查未完成数据文件的 Schema，不能用于发布。
