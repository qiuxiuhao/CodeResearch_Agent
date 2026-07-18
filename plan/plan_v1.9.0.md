# CodeResearch Agent v1.9.0：Evaluation、Bad Case 与 Regression Loop 开发计划

状态：v1.8 正式基线冻结、评测资产审计完成、v1.9 开工前设计冻结
事实基线：v1.8 implementation commit `0bbba875082e9964bae3b7b9e4056c077ec8b1ad`；正式 release identity 为 annotated tag `v1.8.0`
优先技术债：`ALIGNMENT_BENCHMARK_PENDING`
实施范围：v1.9.0-a 至 v1.9.0-f

## 0. 开工前置条件

1. v1.8 独立 implementation commit 与 `v1.8.0` release tag 已建立；v1.9 Dataset/Evaluation provenance必须记录实际运行的完整 commit SHA和Dataset/config hash，不能只保存可移动的分支名。
2. v1.8 基线已在干净提交边界完成后端、前端、build、`scripts/validate.sh` 与 Observability benchmark验收；若v1.9开工前HEAD变化，必须在新commit上重新验收并更新基线。
3. 当前 Alignment 实际为 0 case/0 pair。`ALIGNMENT_BENCHMARK_PENDING` 是 v1.9-a 优先任务；在真实 Gold 冻结前，所有 Alignment Accuracy/F1/Calibration Gate 必须显示 `not_evaluable`，不得使用 Legacy、Scorer、LLM 或 Trace 输出填充。
4. Retrieval 40 case 和 Agent 30 case 都是 synthetic/contract fixture，不得描述成 5 个真实开源仓库的人工质量集。v1.9 必须保存其来源类型并与 human-authored 结果分组报告。
5. 自动 CI 只能运行 `offline_recompute` 与 `deterministic_fixture`，禁止网络、真实 Provider、模型下载、Gold 写回和业务状态修改。
6. Evaluation 必须是独立流程：

```text
IndexBuildGraph      业务事实构建
ResearchAgentGraph   在线研究运行
EvaluationGraph      Dataset → Adapter → Metric → Compare → Gate → Bad Case
```

不得把 Evaluation 状态塞入 ResearchState，也不得用 Checkpoint、Trace 或系统输出替代 Gold。

## 1. 背景与目标

v1.4～v1.8 已提供结构化事实、Hybrid Retrieval、Research Agent、论文代码对齐和统一 Trace，但评测能力仍分散：Retrieval/Agent/Alignment 各有不同 Case/Outcome Schema 和脚本，没有统一 Dataset Version、Run、Adapter、Metric Definition、Baseline Comparison、Regression Gate、Bad Case 生命周期或安全 Replay。

v1.9 建立可持续的闭环：冻结有 provenance 的 Dataset/Gold，用六类 Adapter 在离线、确定性和受控 Live 模式运行，统一计算版本化指标，与兼容 Baseline 做整体和 subgroup 比较；失败案例进入 append-only Bad Case 流程，经人工确认和独立验证后才能提升为新 Regression Dataset Version。

成功标准不是“自动找到并修好所有问题”，而是每个质量结论都能回答：使用哪个代码/数据/索引/模型版本、哪些 case、哪种执行模式、输入是否完整、指标如何计算、Gate 为什么通过/阻断、Bad Case 是否经过人工确认和后续验证。

## 2. 当前评测资产审计

### 2.1 Retrieval

| 项目 | 实际事实 | v1.9 处理 |
| -- | -- | -- |
| Dataset | `evaluation/retrieval/benchmark_v1.jsonl`，40 case：30 Dev + 10 Locked | 作为 `synthetic_fixture` 导入，不伪装成人工真实集 |
| Fixture | `build_fixture.py` 确定性构造 2 repo identity、3 index version 和固定 Entity/Chunk/Edge | 固定 builder/version/content hash，CI 可重建 |
| Gold | entity/chunk IDs、graph path、edge type、unresolved symbol、difficulty/tags | 迁移为 typed RetrievalGold |
| Metrics | Recall@1/5/10、MRR、nDCG@5/10、Graph Path Recall、latency、fallback | 增加 Recall@20、empty、channel/fallback 和完整性语义 |
| Runner | `evaluate_retrieval.py` 只读取外部 predictions | 由 Adapter 负责产出标准 CaseResult；旧脚本保留为兼容入口 |
| 模型边界 | 测试使用 Fake Embedder/Sparse、Mock Reranker；当前环境无 Qdrant/FastEmbed | deterministic 与 live 分开，不把 Mock 指标当真实模型指标 |

当前仓库没有冻结 prediction/result，因此没有可复现的 Retrieval quality baseline 数值。

### 2.2 Research Agent

| 项目 | 实际事实 | v1.9 处理 |
| -- | -- | -- |
| Dataset | `evaluation/agent/benchmark_v1.jsonl`，30 case：20 Dev + 10 Locked | 作为 `synthetic_fixture` 导入 |
| 分布 | 10 direct、15 planned、5 expected partial | 保存 route/failure subgroup |
| Gold | route、required/optional/forbidden tools、Evidence/Edge、budget、sufficiency、terminal status | 迁移为 typed AgentGold |
| Metrics | Task Success、Route、Tool、Evidence、Citation、Replan、Recovery、Budget、Latency/Token | 补齐显式 failure denominator、subgroup 和 completeness |
| Fault | Case Schema 有 `fault_injection`，但 30 case 全部为 null | v1.9-b 新增固定 Fault Profile，不把 failure query 当注入测试 |
| Runner | `evaluate_agent.py` 只读取外部 Outcome | 新 Adapter 运行 fixture graph或读取持久 Run |

当前没有仓库内冻结 Agent outcome，也没有真实 Provider 的 Locked baseline。

### 2.3 Alignment

- `fixture_catalog_v1.json` 只有 4 Dev + 2 Locked 空槽，repo/paper fixture 均为 null。
- `benchmark_v1.jsonl` 只有注释；实际 0 case、0 pair、0 positive、0 negative。
- 没有双人标注、adjudication、真实 Gold、Locked 结果或校准报告。
- Candidate/Final/Abstention/Evidence/Brier/ECE 的 Metric 实现和手算测试存在，但不产生质量事实。

结论：`ALIGNMENT_BENCHMARK_PENDING`。v1.9-a 必须先冻结授权的 repo-paper fixture、Profile generation、标注规则和双人审核流程；系统输出、Legacy Alignment、LLM 或人工 Review 只能辅助定位，不能直接成为最终 Gold。

### 2.4 Answer 与 Citation

- `ResearchAnswer`、Draft/Validated/Final Answer、Citation Validator、Claim Verifier、Finalizer 已存在。
- Citation 可以验证 context/evidence/entity membership，并由事实 Context 覆盖 path/line/page。
- 当前 Claim Verifier 主要以“是否有有效 Citation”判断支持状态，不执行独立语义 entailment Gold 比对。
- 没有独立 Answer Dataset、gold answer points、claim coverage/completeness Gold 或人工 rubric。

因此现有测试证明结构安全和引用有效性，不证明 Answer 语义正确或完整。

### 2.5 Observability

- v1.8 有 Trace completeness/integrity、typed Link、Span lifecycle、Drop、SSE、Access/Redaction 测试。
- 有 `scripts/benchmark_observability.py`，当前实测 Noop/metadata enqueue 性能。
- 没有版本化 Trace fixture dataset、expected span tree Gold、历史性能 artifact 或 Observability Regression Adapter。

Trace 是诊断输入，不是 Gold。partial/unknown Trace 只能生成 `complete=false` 的 MetricResult，不能用于精确业务结论。

### 2.6 Index、Run 与 Checkpoint

- Structured Index 提供不可变 repo/index version、Entity/Edge/Evidence/Chunk、manifest、active version 与失败隔离，可作为 Fixture 事实源。
- ResearchRunStore 提供 route、plan、Tool Observation、Evidence、Budget、Answer、terminal/retry/cancel；Alignment Store 提供 Profile/Candidate/Feature/Score/Decision/Review。
- LangGraph Checkpoint 保存执行 State 和恢复位置。它不是评测结果或 Gold；读取必须受业务权限与 serializer/version约束。
- v1.8 Trace 只保存 metadata/ArtifactRef，不包含 Query/Prompt/源码/正文。因此 `offline_recompute` 必须读取授权的 Dataset/业务 Artifact，不能指望从 Trace 反向恢复全部输入。

## 3. 本阶段目标

v1.9.0 只实现：

1. 统一 Evaluation Dataset/Case/Version/Run/Plan/Result Schema。
2. Dataset Catalog、Frozen Gold、provenance 与 content hash。
3. Index/Retrieval/Agent/Alignment/Answer/Observability 六类 Adapter。
4. 版本化 Metric Engine 与整体/pair/repo/tag/type subgroup 报告。
5. Baseline Comparison 与 Hard/Quality/Performance Regression Gate。
6. Bad Case Analyzer、append-only 生命周期与人工 Triage。
7. Confirmed Bad Case → Regression Case → 新 Dataset Version 的 Promotion。
8. Replay Analysis、Offline Replay 与受控 Live Experiment。
9. 独立 Evaluation Store、Coordinator、Lease、Cancel、Retry 与 progress。
10. Evaluation/Bad Case API、最小 Dashboard 和 deterministic CI command。
11. 优先补齐或明确阻断 `ALIGNMENT_BENCHMARK_PENDING`。

## 4. 非目标

- 不自动修改代码、规则、检索参数、Prompt 或模型配置。
- 不自动提交 Git、创建 PR 或部署修复。
- 不自动修改/接受 Gold；Dataset Frozen 后不可原地更新。
- 不以 LLM Judge 作为主要或唯一指标；可选 Judge 只能是独立辅助 rubric。
- 不默认执行真实 Provider、模型下载、外部网络或 Checkpoint Replay。
- 不从历史 Checkpoint 自动重新执行；LangGraph Replay 是有副作用和费用的真实执行。
- 不在线训练/微调模型、Scorer、Calibrator 或 Reranker。
- 不让自动 Root Cause 建议直接关闭 Bad Case。
- 不建设完整在线标注平台或众包系统。
- 不引入 PostgreSQL、Redis、Celery、Kafka、分布式队列或外部 Evaluation SaaS。
- 不修改 v1.4～v1.8 的事实、排序、Agent/Alignment决策或 Trace 内容策略来“提高指标”。

## 5. 权威边界

```text
Dataset/Gold
= 人工或确定性 Fixture 的期望事实；版本冻结后不可变

Business Store / Run / Checkpoint
= 被评测系统的实际状态和输出

Trace Store
= best-effort 时间线、性能、错误和关联；不是 Gold

Evaluation Store
= Run、Case Result、Metric、Comparison、Gate、Bad Case 与 Promotion
```

Evaluation 只读业务 Store/Trace/Checkpoint，写入独立 Evaluation Store。业务结果、Trace 或人工 Review 不能被隐式提升为 Gold；Gold 只能通过显式标注、审核和新 Dataset Version 冻结。

## 6. Evaluation Schema

新增 `backend/app/evaluation/schemas.py`。全部模型使用 Pydantic v2、`extra="forbid"`、`default_factory`、受限 `JsonValue`、UTC 时间、显式 schema/version/provenance/content hash 和大小限制。

```python
DatasetSplit = Literal["dev", "locked_test", "regression"]
DatasetSource = Literal["human_authored", "confirmed_bad_case", "synthetic_fixture"]
EvaluationMode = Literal["offline_recompute", "deterministic_fixture", "live_experiment"]
EvaluationComponent = Literal[
    "index", "retrieval", "agent", "alignment", "answer", "observability",
]

class EvaluationProvenance(StrictModel):
    schema_version: str
    code_commit_sha: str
    worktree_patch_hash: str | None
    dataset_version_id: str | None
    fixture_version: str | None
    repo_id: str | None
    index_version_id: str | None
    paper_id: str | None
    prompt_versions: dict[str, str]
    model_profiles: dict[str, str]
    provider_revisions: dict[str, str]
    config_hash: str
    random_seed: int | None
    created_at: datetime

class EvaluationDataset(StrictModel):
    schema_version: str
    dataset_id: str
    name: str
    description: str
    component_scope: list[EvaluationComponent]
    owner_scope_hash: str
    status: Literal["draft", "active", "retired"]
    active_version_id: str | None
    created_at: datetime
    updated_at: datetime

class EvaluationDatasetVersion(StrictModel):
    schema_version: str
    dataset_version_id: str
    dataset_id: str
    version: str
    status: Literal["draft", "validating", "frozen", "superseded", "invalid"]
    parent_version_id: str | None
    case_count: int
    split_counts: dict[DatasetSplit, int]
    source_counts: dict[DatasetSource, int]
    schema_hash: str
    content_hash: str
    annotation_policy_version: str
    authorization_scope_hash: str
    provenance: EvaluationProvenance
    created_at: datetime
    frozen_at: datetime | None

class FixtureRef(StrictModel):
    fixture_id: str
    fixture_version: str
    fixture_type: Literal["repository", "paper", "index", "run", "trace", "synthetic"]
    content_hash: str
    repo_id: str | None
    index_version_id: str | None
    paper_id: str | None
    artifact_ref_ids: list[str]

class IndexGold(StrictModel): ...
class RetrievalGold(StrictModel): ...
class AgentGold(StrictModel): ...
class AlignmentGold(StrictModel): ...
class AnswerGold(StrictModel): ...
class ObservabilityGold(StrictModel): ...

EvaluationGold = Annotated[
    IndexGold | RetrievalGold | AgentGold | AlignmentGold |
    AnswerGold | ObservabilityGold,
    Field(discriminator="component"),
]

class EvaluationCase(StrictModel):
    schema_version: str
    case_id: str
    dataset_version_id: str
    split: DatasetSplit
    source: DatasetSource
    component: EvaluationComponent
    fixture_refs: list[FixtureRef]
    repo_id: str
    index_version_id: str
    paper_id: str | None
    input_artifact_ref_id: str
    gold: EvaluationGold
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str]
    annotator_scope_hashes: list[str]
    adjudication_status: Literal["not_required", "pending", "agreed", "adjudicated", "disputed"]
    provenance: EvaluationProvenance
    content_hash: str

class EvaluationPlan(StrictModel):
    schema_version: str
    plan_id: str
    dataset_version_id: str
    mode: EvaluationMode
    components: list[EvaluationComponent]
    adapter_versions: dict[str, str]
    metric_definition_ids: list[str]
    case_ids: list[str]
    baseline_run_id: str | None
    frozen_config_hash: str
    case_concurrency: int
    provider_concurrency: int
    provider_budget: ProviderBudget | None
    external_model_consent: bool
    random_seed: int
    provenance: EvaluationProvenance

class EvaluationRun(StrictModel):
    schema_version: str
    run_id: str
    plan_id: str
    dataset_version_id: str
    mode: EvaluationMode
    status: Literal[
        "queued", "preparing", "running", "aggregating", "comparing",
        "ready", "active", "failed", "cancelled", "superseded",
    ]
    attempt_number: int
    retry_of_run_id: str | None
    cancel_requested: bool
    lease_owner_hash: str | None
    case_counts: dict[str, int]
    error_code: str | None
    provenance: EvaluationProvenance
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

class CaseResult(StrictModel):
    schema_version: str
    result_id: str
    evaluation_run_id: str
    case_id: str
    component: EvaluationComponent
    status: Literal["queued", "running", "passed", "failed", "error", "skipped", "cancelled"]
    complete: bool
    incomplete_reason_codes: list[str]
    business_run_id: str | None
    trace_id: str | None
    output_artifact_refs: list["EvaluationArtifactRef"]
    failure_code: str | None
    latency_ms: float | None
    token_usage: dict[str, int]
    estimated_cost: float | None
    content_hash: str
    started_at: datetime | None
    finished_at: datetime | None

class MetricDefinition(StrictModel):
    schema_version: str
    metric_definition_id: str
    name: str
    version: str
    component: EvaluationComponent
    direction: Literal["higher_is_better", "lower_is_better", "zero_required"]
    aggregation: Literal["count", "ratio", "mean", "macro_mean", "percentile", "calibration"]
    denominator_policy: str
    empty_input_policy: Literal["zero", "one", "null", "error"]
    requires_complete_input: bool
    subgroup_keys: list[str]
    config_hash: str

class MetricResult(StrictModel):
    schema_version: str
    metric_result_id: str
    evaluation_run_id: str
    metric_definition_id: str
    split: DatasetSplit | Literal["all"]
    subgroup: dict[str, str]
    value: float | None
    numerator: float | None
    denominator: float | None
    sample_count: int
    complete: bool
    incomplete_reason_codes: list[str]
    confidence_interval: tuple[float, float] | None
    artifact_ref_ids: list[str]
    computed_at: datetime

class RegressionComparison(StrictModel):
    schema_version: str
    comparison_id: str
    baseline_run_id: str
    candidate_run_id: str
    dataset_version_id: str
    compatibility: Literal["compatible", "partially_compatible", "incompatible"]
    incompatibility_reasons: list[str]
    metric_deltas: list[MetricDelta]
    subgroup_deltas: list[MetricDelta]
    status: Literal["pending", "ready", "invalid"]
    created_at: datetime

class RegressionGate(StrictModel):
    schema_version: str
    gate_id: str
    comparison_id: str
    gate_config_version: str
    hard_invariants: list[GateRuleResult]
    quality_rules: list[GateRuleResult]
    performance_rules: list[GateRuleResult]
    verdict: Literal["passed", "blocked", "indeterminate"]
    reason_codes: list[str]
    evaluated_at: datetime

class BadCase(StrictModel):
    schema_version: str
    bad_case_id: str
    source_result_id: str
    source_evaluation_run_id: str
    source_trace_id: str | None
    case_id: str
    component: EvaluationComponent
    symptom: BadCaseSymptom
    suggested_root_causes: list[RootCauseSuggestion]
    confirmed_root_cause: BadCaseRootCause | None
    status: Literal["open", "triaged", "confirmed", "fixing", "fixed", "verified", "closed", "rejected"]
    revision: int
    severity: Literal["low", "medium", "high", "critical"]
    evidence_ref_ids: list[str]
    fix_commit_sha: str | None
    verification_run_id: str | None
    created_at: datetime
    updated_at: datetime

class BadCaseEvent(StrictModel):
    schema_version: str
    event_id: str
    bad_case_id: str
    sequence: int
    from_status: str | None
    to_status: str
    actor_scope_hash: str
    based_on_revision: int
    reason_code: str
    note_hash: str | None
    artifact_ref_ids: list[str]
    created_at: datetime

class RegressionCasePromotion(StrictModel):
    schema_version: str
    promotion_id: str
    bad_case_id: str
    source_dataset_version_id: str
    target_dataset_version_id: str
    new_case_id: str
    source_trace_id: str | None
    fix_commit_sha: str
    gold_review_status: Literal["pending", "approved", "rejected"]
    fixture_minimization_status: Literal["pending", "complete", "not_possible"]
    created_at: datetime

class ReplayManifest(StrictModel):
    schema_version: str
    replay_manifest_id: str
    replay_type: Literal["analysis", "offline", "live"]
    source_run_id: str
    source_trace_id: str | None
    source_checkpoint_id: str | None
    required_artifact_refs: list[str]
    fixed_versions: EvaluationProvenance
    readiness: Literal["ready", "not_ready", "consent_required", "artifact_missing"]
    reason_codes: list[str]
    external_model_consent: bool
    budget: ProviderBudget | None
    execution_requested: bool
    content_hash: str

class EvaluationArtifactRef(StrictModel):
    schema_version: str
    artifact_ref_id: str
    artifact_type: Literal[
        "dataset", "fixture", "gold", "prediction", "run", "trace", "checkpoint",
        "index_manifest", "retrieval_result", "answer", "alignment_decision", "report",
    ]
    artifact_id: str
    content_hash: str
    repo_id: str | None
    index_version_id: str | None
    paper_id: str | None
    authority: Literal["gold", "business_fact", "derived_result", "diagnostic"]
```

不得在 `JsonValue` attributes 中塞完整 State、任意对象、Prompt、模型响应或源码。建议硬限制：Case input/gold 各 64KiB、Case Result 128KiB、每 Run 10,000 case、每 Case 200 ArtifactRef、tags 50、错误/原因码 100；大结果通过受控 ArtifactRef 分页读取。

## 7. Dataset、Fixture 与 Gold

### 7.1 Split 与来源

```text
split  = dev | locked_test | regression
source = human_authored | confirmed_bad_case | synthetic_fixture
```

- Dev 用于配置、阈值、Prompt 或方法选择。
- Locked Test 只在 candidate config/model profile冻结后运行；不能进入 fit、threshold search 或 prompt selection。
- Regression 只包含已确认并最小化、可离线复现的历史 Bad Case。
- source 必须参与 subgroup 报告，禁止将 synthetic 与 human-authored 汇总后只报告单一“准确率”。

### 7.2 不可变与版本

```text
draft → validating → frozen → superseded
                 └→ invalid
```

Frozen Version 只读。任何 Case、Gold、Fixture、annotation、split 或授权变化都创建新 Dataset Version；不能 UPDATE 旧行。Case ID 在 Dataset Version 内唯一，content hash覆盖规范化 input/gold/fixture/split/source/provenance。

Locked Test 的访问和结果读取需要独立 scope；Runner 只能按 Plan 中冻结的 Case ID读取，不能把 Locked 原文发送给未授权 Provider。Live 结果不会自动替换 Frozen Baseline。

### 7.3 Gold 规则

- Gold 不得由被评测系统、Legacy Alignment、当前 Scorer、LLM Judge 或 Trace 自动生成。
- LLM 只能辅助定位 Evidence/候选；最终 Gold 必须人工确认或来自可证明的 deterministic fixture。
- 每个 Case 固定 repo/index/paper fixture 与 content hash；索引版本变化必须新建 Dataset Version。
- human-authored 保存 annotator scope HMAC、annotation policy、Evidence 和 adjudication；不保存姓名、邮箱或明文身份。
- disputed Case 不进入主 Gate，可进入独立分析。

### 7.4 Alignment Gold 补齐

优先流程：

```text
冻结 6 个授权 repo-paper pair（4 Dev + 2 Locked）
→ 固定 repo/index/paper/Profile generation
→ 第一标注者阅读论文与代码
→ 第二标注者独立标注
→ 分歧 adjudication
→ Gold/负例/Evidence 完整性校验
→ 冻结新 alignment Dataset Version
→ 运行 Legacy 和 v1.7 Baseline
```

目标沿用 v1.7 计划的 92 case（72 positive + 20 unalignable/hard negative），但这是待完成验收目标，不是当前事实。若授权或标注资源不足，必须继续保留 `ALIGNMENT_BENCHMARK_PENDING`，并让 Alignment Quality Gate 为 `indeterminate/not_evaluable`；不得降低数量后静默宣称技术债关闭。

## 8. 评测模式

### 8.1 `offline_recompute`

读取冻结 prediction、Run、Decision、Trace summary 或 Case Result，重新计算 Metric/Comparison。不得调用业务模型、Provider、Tool、Graph或写回业务 Store。适合 Metric 版本升级和历史报告复算。

### 8.2 `deterministic_fixture`

使用临时/隔离 SQLite、Fake Embedder、Mock Provider、固定 Checkpointer、固定 clock/seed 和 deterministic sampler执行业务适配器。允许执行本地业务流程，但不能访问网络或持久业务 DB。CI 只运行此模式和 offline。

### 8.3 `live_experiment`

真实 Provider/模型的受控实验，必须同时满足：显式 mode permission、external consent、固定 Provider/model/revision/Prompt、版本化预算、独立 Run/Trace/Store namespace、case/provider concurrency cap 和审计。Live 失败不能修改 Gold或 Locked Baseline；成为 Baseline 需要显式审批和 compatible frozen comparison。

## 9. Component Adapter

统一接口：

```python
class EvaluationAdapter(Protocol):
    component: EvaluationComponent
    adapter_version: str

    async def prepare(self, case: EvaluationCase, context: EvaluationExecutionContext) -> None: ...
    async def execute(self, case: EvaluationCase, context: EvaluationExecutionContext) -> CaseResult: ...
    def extract_metrics(self, case: EvaluationCase, result: CaseResult) -> list[MetricInput]: ...
```

| Adapter | 输入 Gold | 读取/执行 | 输出 Artifact | 核心指标 | Failure/Mock/隔离 |
| -- | -- | -- | -- | -- | -- |
| `IndexEvaluationAdapter` | Entity/Edge/Evidence/Manifest、稳定 ID、unresolved | offline 读 snapshot 或 deterministic rebuild | manifest/entity/edge diff | ID stability、entity/edge recall、unresolved preservation、activation isolation | 临时 Index DB；parser failure fixture；固定 repo/version |
| `RetrievalEvaluationAdapter` | entity/chunk/path/rank relevance | offline prediction 或隔离 RetrievalService | ranked candidates、channel/graph/rerank summary | Recall@1/5/10/20、MRR、nDCG、Graph Path、Empty/Fallback、Latency | Fake Dense/Sparse/Reranker；live profile显式；禁止跨repo/version |
| `AgentEvaluationAdapter` | route/plan/tool/evidence/terminal/budget | offline Run View 或 deterministic Research Graph；live需consent | route/plan/tool/evidence/answer/run refs | Task Success、Route、Plan、Tool、Evidence、Citation、Recovery、Budget、Latency/Token | MockProvider/Checkpointer/FaultProfile；每Case独立thread/run |
| `AlignmentEvaluationAdapter` | profile/selection/relation/no-implementation/evidence | offline Alignment Run 或隔离 deterministic pipeline | candidate/score/decision/verification refs | Candidate Recall、Pair F1、Exact Set、Selective/Abstention、Evidence、Brier/ECE | 无Gold则not_evaluable；固定model profile/pair/version |
| `AnswerEvaluationAdapter` | answer points、claims、required/forbidden evidence/citations | offline Answer 或 deterministic finalizer；live generator可选 | claim/citation/support summary | Claim Coverage、Supported Claim、Citation Validity、Completeness、Evidence-only correctness | 规则优先；optional human/LLM rubric单独报告；不把Judge作为主指标 |
| `ObservabilityEvaluationAdapter` | expected trace shape/link/integrity/privacy/perf | 读Trace或运行InMemory/SQLite fixture | bounded trace summary、benchmark result | Completeness、Integrity、Missing、Link、Redaction、Drop、Overhead | partial标complete=false；禁止读取内容；Trace DB隔离 |

Adapter 不拥有 Gold，不修改 Dataset，不直接决定 Gate。任何业务异常转换为 typed CaseResult `error/failed/complete=false`，不得导致其他 Case 丢失。

## 10. Metric Engine

所有 Metric 必须有 `MetricDefinition(version, direction, denominator_policy, empty_input_policy, completeness requirement)`。同名算法或 denominator变化必须升级版本，旧结果保留。

### 10.1 Retrieval

- Recall@1/5/10/20。
- MRR。
- nDCG@5/10/20。
- Graph Path Recall。
- Empty Result Rate、channel fallback/availability。
- P50/P95 total/channel latency。

### 10.2 Agent

- Task Success。
- Route Accuracy、Plan Validity。
- Tool Selection、Tool Argument Validity、Invalid Tool Call。
- Evidence Sufficiency、Citation Validity、Unsupported Claim。
- Recovery、Replan、Budget compliance/exhaustion。
- P50/P95 latency、tool/provider calls、Token/known cost。

### 10.3 Alignment

- Candidate Recall@5/10/20、MRR。
- Relation-aware Pair Micro/Macro F1、Exact Set。
- Selective Accuracy、Coverage、Abstention Precision/Recall。
- no-implementation Precision/Recall/F1。
- Paper/Code Evidence Precision、Unsupported Alignment Rate。
- Candidate probability Brier/ECE、fixed bins与sample count。

### 10.4 Answer

- Claim Coverage。
- Supported Claim Rate / Unsupported Claim Rate。
- Citation Validity 与行号/页码事实匹配。
- Answer Completeness（人工/确定性 gold points）。
- Evidence-only correctness。
- optional human rubric 与 optional LLM rubric独立列出，不进入默认 Hard Gate。

### 10.5 Observability

- Trace Completeness。
- Integrity Flag Rate、Missing Span/Event、Orphan/Abandoned。
- Link Validity。
- Redaction/Secret Leakage（必须为0）。
- Queue/Store/Exporter Drop/Failure Rate。
- Noop/metadata P50/P95 overhead与writer throughput。

所有指标报告 all + split + source + repo/pair + component/type/tag/difficulty subgroup。必须同时返回 sample count、denominator、complete、failure count；小样本不输出伪精确置信区间。

## 11. Baseline Comparison 与 Regression Gate

Comparison 只有在 Dataset Version、Case set、Metric Definition、Adapter major version、repo/index/paper fixture、执行 mode 与关键 model/config profile可比时才为 compatible。部分不兼容只能按共同子集展示，不能作为自动 Gate。

### 11.1 Hard Invariant Gate

必须阻断：

```text
跨 repo/index/paper 泄漏 > 0
Invalid Tool Call > 0
非法 Citation > 0
未知 Alignment Candidate > 0
Secret/禁止内容泄漏 > 0
Recorder On/Off 业务输出、排序或状态不一致 > 0
Gold/Frozen Dataset 被修改 > 0
Live 无 consent/超预算调用 > 0
```

Hard input incomplete 时 verdict 为 `indeterminate` 并阻断 promotion，不能当 passed。

### 11.2 Quality Gate

按 Metric direction 比较 absolute delta、relative delta 和 subgroup delta。Overall 改善不能覆盖任一关键 repo/tag/relation/query type 的显著退化。阈值必须在 v1.9-a 用真实 Baseline、样本量与方差冻结，记录 gate config version；本计划不预写最终数值。

### 11.3 Performance Gate

比较 P50/P95 latency、Token、tool calls、replans、provider calls、known cost 和 Trace overhead。冷/热 cache、硬件、并发、mode不同的结果不可直接 Gate。性能缺样本或 telemetry incomplete 时为 indeterminate。

## 12. Bad Case Model 与 Analyzer

### 12.1 Symptom

```text
wrong_answer | partial_answer | empty_result | wrong_alignment |
invalid_citation | unsupported_claim | timeout | budget_exhausted |
unexpected_abstention | false_accept | trace_incomplete
```

### 12.2 Root Cause

```text
dataset_invalid | profile_extraction_error | index_missing_entity |
index_wrong_edge | retrieval_miss | retrieval_rank_error |
graph_path_missing | reranker_regression | router_error | plan_invalid |
tool_selection_error | tool_argument_error | tool_empty |
evidence_checker_error | context_truncation | provider_error |
alignment_candidate_miss | alignment_feature_error |
alignment_scoring_error | calibration_error |
abstention_threshold_error | nondeterminism | telemetry_drop | unknown
```

Analyzer 只能依据 CaseResult、Metric、Trace metadata、ArtifactRef 和 known failure code输出带 Evidence 的 `RootCauseSuggestion(confidence, reason_codes, evidence_refs)`。它不得自动设置 `confirmed_root_cause`、修改代码/Prompt/Gold或推进到 fixed/closed。

## 13. Bad Case 生命周期

```text
open → triaged → confirmed → fixing → fixed → verified → closed
  └──────────────────────────────────────────────────→ rejected
```

- 每次状态变化追加 `BadCaseEvent`，不 UPDATE/删除历史事件。
- `based_on_revision` 乐观锁；旧 revision 返回 409。
- `fixed` 只表示关联了 fix commit/变更，绝不等于指标已恢复。
- `verified` 必须关联后续 compatible Evaluation Run/Case Result，且目标 Gate通过。
- `closed` 必须有 verification run、verified event、最终 root cause 和 Evidence。
- rejected 保存原因，不删除原 Case/Trace。
- Trace、Evidence、Fix Commit只保存 ID/hash/ref；不复制Prompt、源码或Checkpoint。

## 14. Regression Case Promotion

```text
Confirmed Bad Case
→ Gold 合法性与授权审核
→ 最小化 deterministic Fixture
→ 创建 Regression Case
→ 创建新的 draft Dataset Version
→ 全量校验并 frozen
```

Promotion 必须保存原 `bad_case_id`、source result/trace、fix commit、原/new Dataset Version、Gold reviewer和fixture hash。旧 Frozen Dataset 不变。不能离线稳定重现、依赖随机 Provider输出或Gold有争议的 Case不得 promoted；可保留 Bad Case但 promotion为 rejected/pending。

## 15. Replay 边界

### 15.1 Replay Analysis

只读取 Trace/Run/Metric/ArtifactRef重建时间线和比较，不执行 Graph、Tool、Provider或业务写入。

### 15.2 Offline Replay

使用冻结 Artifact、Fake/Mock、临时 DB 与固定 seed重新计算组件输出。必须无网络、无付费、无业务状态修改；输出新 Evaluation CaseResult/Trace，不覆盖原结果。

### 15.3 Live Replay

从原输入或受支持 Checkpoint创建新的隔离业务 Run。必须显式 consent、固定 Provider/model/revision/Prompt、固定预算、新 `run_id`、新 `trace_id`，并用 `replay_of` Link/ArtifactRef关联原 Run。保留原 Run，不写 Gold、不切换生产 active Deployment。

LangGraph 从 Checkpoint 后恢复会重新执行后续 LLM/API/Interrupt，是实际执行而非只读调试；未授权、serializer不兼容、Artifact缺失或版本不一致时 ReplayManifest必须 `not_ready`。

## 16. Evaluation Store

使用独立 `data/evaluation.sqlite3`，不修改 structured index、Research、Alignment、Observability 或 Checkpoint DB。至少包含：

```text
evaluation_datasets
evaluation_dataset_versions
evaluation_cases
evaluation_runs
evaluation_run_leases
evaluation_plans
evaluation_case_results
evaluation_metric_definitions
evaluation_metric_results
evaluation_comparisons
regression_gates
bad_cases
bad_case_events
bad_case_evidence_refs
regression_case_promotions
evaluation_replay_manifests
evaluation_artifact_refs
evaluation_idempotency_keys
```

规则：

- 编号 migration、`PRAGMA user_version`、WAL、foreign keys、busy timeout和短事务。
- Frozen Dataset/Case由 trigger/service guard禁止 UPDATE/DELETE；新版本通过复制引用+新增变更构建。
- Run 状态：`queued → preparing → running → aggregating → comparing → ready → active → superseded`，构建态可到 failed/cancelled。
- failed/cancelled 同输入允许新 attempt并保留 retry chain；成功结果按 dataset/plan/config/code hash幂等复用。
- CaseResult 分阶段写入，单 Case失败不回滚其他 Case；默认查询只读取 ready/active。
- BadCase event sequence与revision在短事务分配。
- retention 只删除无 Baseline/Gate/BadCase/Promotion引用的可重建 Run artifact；Frozen Dataset、Gold、Gate和audit event默认不自动删除。
- Evaluation Store故障不能修改业务 Store或原 Trace，但 Evaluation Run应明确failed/partial，不能假装通过。

## 17. EvaluationRunCoordinator

新增 `backend/app/services/evaluation_run_coordinator.py`，采用 FastAPI lifespan + managed asyncio Task Manager + SQLite Lease：

```text
POST queued Run
→ claim Lease
→ prepare frozen plan/cases
→ bounded case workers
→ per-case Adapter execution
→ Metric aggregation
→ optional Comparison/Gate
→ ready/active
```

Coordinator 负责 heartbeat、lease expiry recovery、cancel、graceful shutdown、attempt retry、case isolation、progress和late result token校验。默认 case concurrency有限；live provider concurrency更低且由统一 Budget/Consent控制。取消只阻止新 Case并在安全边界停止，已完成 CaseResult保留；ready/active不允许取消。

## 18. Trace 接入

- Evaluation Run 创建独立 `evaluation.run` Trace；需以版本化方式扩展 v1.8 Trace taxonomy，不改变旧 Trace解释。
- 同进程短 Case可建 Child Span；独立/长业务 Run创建新 Trace并以 `evaluates`/`replay_of` typed Link或ArtifactRef关联 Evaluation Case Span。
- 原业务 Trace只读，不追加/改写其 Span/Event/completeness；关联从新 Evaluation Trace一侧保存。
- CaseResult 保存 source/new trace ID。原 Trace partial/unknown时相关 MetricResult `complete=false`。
- Trace不能作为Gold，也不能从Trace count推导语义正确性。
- Evaluation自身必须遵守v1.8 metadata-only、Redaction、Access、Queue/Store失败隔离和suppression规则。

## 19. API 设计

路由默认关闭：

```text
EVALUATION_ENABLED=false
EVALUATION_API_ENABLED=false
EVALUATION_LIVE_ENABLED=false
```

设计接口：

```text
POST /evaluations/runs
GET  /evaluations/runs/{run_id}
POST /evaluations/runs/{run_id}/cancel
GET  /evaluations/runs/{run_id}/results
GET  /evaluations/runs/{run_id}/metrics

POST /evaluations/comparisons
GET  /evaluations/comparisons/{comparison_id}

GET  /bad-cases
GET  /bad-cases/{bad_case_id}
POST /bad-cases/{bad_case_id}/triage
POST /bad-cases/{bad_case_id}/confirm
POST /bad-cases/{bad_case_id}/mark-fixed
POST /bad-cases/{bad_case_id}/verify
POST /bad-cases/{bad_case_id}/promote

GET /evaluation/datasets
GET /evaluation/datasets/{dataset_id}
GET /evaluation/datasets/{dataset_id}/versions/{version_id}
```

要求：

- 统一 `EvaluationAccessPolicy`，至少区分 dataset reader、runner、live runner、gold reviewer、bad-case triager和admin。
- caller hash不是授权；无权与不存在统一404。
- POST使用caller scope + Idempotency-Key + canonical request hash；冲突409。
- cursor分页、时间/状态/component/split/source/tag/repo过滤、单响应2MiB、case/result page上限200。
- live请求必须mode permission + consent + budget + provider profile；缺一拒绝。
- Locked Test、Gold、diagnostic Trace和Checkpoint分别做权限检查。
- 稳定错误码至少包括 `evaluation_disabled`、`evaluation_api_disabled`、`evaluation_live_disabled`、`dataset_not_frozen`、`dataset_version_conflict`、`gold_invalid`、`evaluation_run_not_found`、`evaluation_busy`、`evaluation_cancel_not_allowed`、`comparison_incompatible`、`gate_indeterminate`、`bad_case_conflict`、`promotion_not_ready`、`replay_not_ready`、`live_consent_required`、`evaluation_response_too_large`。

## 20. 最小前端

- Evaluation Dashboard：Run、mode、dataset version、status、progress、quality/performance summary。
- Baseline Comparison：absolute/relative delta、overall/subgroup、compatibility与incomplete。
- Regression Gate：Hard/Quality/Performance rule、blocked原因。
- Bad Case List/Detail：symptom、suggestion、人工root cause、events、Trace/Evidence/Fix/Verification。
- Dataset Version View：split/source/count/hash/frozen/provenance；Gold内容按权限展示。
- Promotion Flow：Gold审核、fixture最小化、新Version preview，不能直接修改Frozen Version。
- Trace Link：跳转v1.8 Explorer，不内联禁止内容。

不实现完整标注平台；第一版Gold编辑/双标可以通过版本化JSONL+validator+review manifest完成，前端只展示和执行受控状态操作。

## 21. CI Regression Command

新增建议入口：

```bash
python scripts/evaluate_regression.py \
  --mode deterministic_fixture \
  --dataset-version <frozen-version> \
  --baseline-run <baseline-run-id> \
  --gate-config <gate-config-version> \
  --output <artifact-path>
```

CI 只使用 regression +小型 synthetic locked subset、Mock/Fake、临时 Store和固定seed；不得下载模型或访问网络。Hard invariant blocked、Gate blocked/indeterminate、Dataset/Gold hash变化或业务状态被修改时返回非零。完整真实仓库/Live suite在受控手动或定时环境运行，不拖垮每次PR。

## 22. 推荐目录与文件边界

### 22.1 新增

```text
backend/app/evaluation/
  __init__.py
  schemas.py
  stable_ids.py
  dataset_catalog.py
  metric_engine.py
  comparator.py
  regression_gate.py
  adapter.py
  adapters/
    index.py
    retrieval.py
    agent.py
    alignment.py
    answer.py
    observability.py
  bad_case_analyzer.py
  bad_case_service.py
  promotion_service.py
  replay_service.py
  evaluation_service.py
  access_policy.py
  api.py

backend/app/persistence/
  evaluation_store.py
  evaluation_migrations/001_evaluation.sql

backend/app/services/evaluation_run_coordinator.py

evaluation/catalog/
evaluation/regression/
tests/evaluation/
scripts/evaluate_regression.py
frontend/src/features/evaluation/
docs/evaluation_v1.9.0.md
```

### 22.2 受控修改

- `backend/app/main.py`：注册API/lifespan；旧运行时顺序和故障隔离不变。
- 现有 benchmark/metrics/scripts：只增加兼容 Adapter，不改变旧计算结果。
- v1.8 Trace taxonomy：仅版本化增加evaluation operation/link，不放宽内容策略。
- frontend router/AppShell：增加Dashboard；旧Trace/Analysis页面不变。
- `pyproject.toml`：第一版不新增强制依赖。

禁止修改事实ID、Retrieval排序、Agent Graph条件、Alignment scorer/threshold/Gold、Provider consent/budget语义和v1.8 Redaction规则来迎合Gate。

## 23. 分阶段实施

### v1.9.0-a：Schema、Dataset Catalog、Metric Contract、Alignment Gold 方案与 Mock Runner

- 输入：正式v1.8 commit、现有70个synthetic case、空Alignment catalog、现有Metric函数。
- 输出：严格Schema、稳定ID/hash、Frozen Dataset Version、typed Gold、MetricDefinition、legacy dataset importer、Mock Runner、Alignment双标工具/validator与授权fixture清单。
- 修改文件：新增evaluation schemas/catalog/metric contract、evaluation catalog、tests；不执行业务Graph。
- 新增依赖：无。
- 测试：Schema round-trip/size、dataset version、frozen immutability、Gold/fixture integrity、split/source隔离、Locked leakage、metric hand calculation、旧40/30 case无损导入。
- 验收：当前资产被准确标为synthetic；Alignment仍空时Gate为not_evaluable；若Gold完成则6 pair/92 case双标和hash全部校验；阈值搜索范围与Metric版本冻结。
- 回滚点：删除新Catalog/Schema；旧评测脚本继续可用。

### v1.9.0-b：六类 Component Adapter

- 输入：Frozen Dataset/Metric合同、v1.4～v1.8只读Service。
- 输出：Index/Retrieval/Agent/Alignment/Answer/Observability Adapter、standard CaseResult和FaultProfile。
- 修改文件：新增adapters与component integration tests；旧Service只通过公开只读入口调用。
- 新增依赖：无。
- 测试：adapter isolation、repo/version、partial failure、Mock/Fake、Answer结构/语义Gold分离、Trace incomplete、business Store无mutation。
- 验收：六类Adapter在offline或deterministic至少一种模式可运行；无Gold组件明确not_evaluable；自动测试无网络。
- 回滚点：按component flag关闭Adapter；业务服务无依赖。

### v1.9.0-c：Comparator、Regression Gate、Baseline与分组报告

- 输入：CaseResult、MetricDefinition、兼容Baseline Run。
- 输出：Metric Engine、overall/split/source/subgroup报告、Comparison、Hard/Quality/Performance Gate和冻结gate config。
- 修改文件：新增metric_engine/comparator/gate、报告脚本/tests。
- 新增依赖：无，统计使用标准库；需要新库必须单独审批。
- 测试：手算、absolute/relative、direction、denominator、subgroup regression、incompatible baseline、incomplete/CI小样本、hard invariant。
- 验收：Overall不能掩盖关键subgroup；hard violation阻断；incomplete为indeterminate；阈值由实际Baseline冻结而非计划伪造。
- 回滚点：只生成报告、不启用自动Gate。

### v1.9.0-d：Bad Case Analyzer、生命周期、Triage 与 Promotion

- 输入：failed/blocked CaseResult、Trace/Evidence refs、Dataset Catalog。
- 输出：suggestion-only Analyzer、append-only BadCase/Event、revision lock、人工Triage、Promotion draft/new Dataset Version。
- 修改文件：新增bad_case/promotion service、Store contract和tests。
- 新增依赖：无。
- 测试：symptom/root cause、stale revision、非法transition、fixed not verified、close requires run、promotion creates new version、no Gold overwrite。
- 验收：自动建议不能确认root cause；每个状态可审计；Promotion可追溯且旧Frozen不变。
- 回滚点：停止创建新BadCase；已有事件只读保留。

### v1.9.0-e：Offline Replay、受控 Live Experiment、Manifest 与 Trace Link

- 输入：ArtifactRef、Run/Checkpoint权限、Provider consent/budget、v1.8 Trace。
- 输出：Replay Analysis、Offline Replay、Live readiness/执行边界、新Run/Trace Link与隔离结果。
- 修改文件：新增replay service、Trace taxonomy小版本扩展和tests；不改变Research/Alignment恢复规则。
- 新增依赖：无。
- 测试：offline无网络、artifact missing、checkpoint unsafe、live consent/budget、new IDs、original preserved、provider concurrency、cancel/partial。
- 验收：默认只读/offline；Live必须显式授权且不写Gold/production active；Trace incomplete传播到Metric。
- 回滚点：`EVALUATION_LIVE_ENABLED=false`，保留offline/analysis。

### v1.9.0-f：Store、Coordinator、API、Dashboard、CI Gate、文档与完整回归

- 输入：a～e稳定合同。
- 输出：独立SQLite/migration、Lease Coordinator、API、Dashboard、CI command、Baseline/BadCase报告和runbook。
- 修改文件：新增store/migration/coordinator/api/frontend/scripts/docs，仅按22.2受控修改main/router。
- 新增依赖：无。
- 测试：migration、lease/recovery/retry/cancel、case/provider cap、API access/idempotency/pagination、Dashboard、CI deterministic、Store failure、full regression。
- 验收：CI小套件确定性且无网络；Live默认关；Gate/BadCase/Promotion闭环可演示；完整后端/前端/build/validate通过。
- 回滚点：关闭Evaluation API/Coordinator/UI；独立DB可保留只读或在确认后删除，业务Store不受影响。

## 24. 测试计划

### 24.1 Dataset 与 Gold

- `test_frozen_dataset_version_is_immutable`
- `test_case_or_gold_change_creates_new_dataset_version`
- `test_locked_test_never_enters_fit_or_threshold_selection`
- `test_gold_cannot_be_generated_by_system_under_test`
- `test_fixture_repo_index_paper_hashes_are_fixed`
- `test_annotator_identity_is_hashed`
- `test_alignment_empty_dataset_keeps_pending_gate`
- `test_alignment_double_annotation_and_adjudication_required`

### 24.2 Adapter 与 Metric

- `test_six_component_adapters_use_repo_version_isolation`
- `test_adapter_failure_isolated_to_one_case`
- `test_offline_adapter_does_not_execute_business_flow`
- `test_deterministic_adapter_uses_mock_and_fixed_checkpoint`
- `test_metric_hand_calculation_and_denominator_policy`
- `test_overall_and_subgroup_metrics_are_both_reported`
- `test_incomplete_trace_produces_incomplete_metric`
- `test_llm_judge_is_not_primary_metric`

### 24.3 Comparison 与 Gate

- `test_comparison_requires_compatible_dataset_and_metric_versions`
- `test_absolute_and_relative_delta`
- `test_subgroup_regression_blocks_quality_gate`
- `test_cross_repo_leak_blocks_hard_gate`
- `test_invalid_tool_call_blocks_hard_gate`
- `test_secret_leak_blocks_hard_gate`
- `test_incomplete_hard_input_is_indeterminate`
- `test_performance_gate_separates_cold_and_warm_runs`

### 24.4 Bad Case 与 Promotion

- `test_bad_case_events_are_append_only`
- `test_bad_case_conflicts_on_stale_revision`
- `test_fixed_is_not_verified`
- `test_verified_requires_compatible_evaluation_run`
- `test_closed_requires_verification_run`
- `test_analyzer_suggestion_does_not_confirm_root_cause`
- `test_promotion_creates_new_dataset_version`
- `test_promotion_preserves_bad_case_trace_and_fix_commit`
- `test_promotion_never_overwrites_gold`

### 24.5 Replay、Coordinator 与 API

- `test_offline_replay_has_no_network`
- `test_live_replay_requires_consent_budget_and_permission`
- `test_live_replay_creates_new_run_and_trace`
- `test_replay_never_overwrites_original_run`
- `test_coordinator_claims_run_once`
- `test_expired_evaluation_lease_recovers`
- `test_failed_run_can_retry_same_plan`
- `test_cancel_stops_new_cases_at_safe_boundary`
- `test_provider_concurrency_is_bounded`
- `test_evaluation_api_defaults_disabled`
- `test_locked_gold_and_trace_access_are_separate`
- `test_ci_regression_is_deterministic_and_offline`
- `test_evaluation_never_mutates_business_store_or_trace`

此外每阶段必须运行受影响旧测试；v1.9-f运行完整后端、前端、build和`scripts/validate.sh`。自动测试禁止网络、模型下载和付费Provider。

## 25. 风险与缓解

| 风险 | 影响 | 缓解/待决策 |
| -- | -- | -- |
| v1.8基线后继续漂移 | Evaluation provenance指向错误代码 | 每次Run固定完整commit SHA/config hash；HEAD变化重新验收，不只记录分支/tag |
| Gold错误 | 错误Gate和错误修复方向 | 双标/adjudication、Evidence、版本化、disputed不进主Gate |
| Benchmark泄漏 | Locked失去意义 | split权限、访问审计、fit配置禁止Locked、变更升版本 |
| Dataset过拟合 | 只优化小fixture | source/repo subgroup、未来真实多仓库扩展、Locked一次性策略 |
| 仓库分布差异 | Overall掩盖局部失败 | macro by repo/pair/tag/type和关键subgroup Gate |
| `ALIGNMENT_BENCHMARK_PENDING` | 无法评估Alignment质量 | v1.9-a优先补6 pair/92 case；未完成则not_evaluable |
| Alignment标注成本 | 延迟质量闭环 | 授权清单、分批双标、工具只辅助定位、不自动Gold |
| LLM Judge偏差 | 自洽但错误的高分 | optional独立报告，确定性/人工Gold为主 |
| Replay产生费用/外发 | 成本和隐私事故 | 默认offline、live flag/permission/consent/budget/concurrency |
| Live不稳定 | 回归结果不可复现 | 固定revision/seed/config，重复实验单独报告，不替换Locked |
| Trace不完整 | 性能/失败结论不精确 | complete flag、integrity统计、Gate indeterminate |
| Bad Case误归因 | 修错组件 | suggestion-only、人工confirm、Evidence、revision/event |
| Regression无限增长 | CI变慢、维护成本高 | 最小化、去重、分层suite、retired但保留历史 |
| SQLite并发 | writer busy/部分结果 | 独立DB、Lease、短事务、bounded workers、case staging |
| CI时间过长 | 开发反馈慢 | 小deterministic regression每PR，完整suite定时/手动 |
| Evaluation影响业务 | 活跃版本/Run被污染 | 临时DB/namespace、只读Adapter、no mutation tests |
| 指标版本漂移 | 历史比较失真 | MetricDefinition/version/config hash与compatibility check |
| Frozen数据误删 | Baseline不可复现 | FK/reference guard、retention legal hold、显式管理员操作 |

待冻结决策：正式v1.8 SHA/tag、首批真实repo-paper授权、Alignment标注者/仲裁流程、Answer Gold rubric、真实多仓库Dataset规模、Metric Definition初版、Gate阈值/关键subgroup、Baseline promotion权限、Evaluation retention、case/provider concurrency、Live pricing profile、local/admin认证来源和CI时限。

## 26. Definition of Done

v1.9.0 只有同时满足以下条件才完成：

1. 基于独立提交、干净验收并记录完整SHA的v1.8基线；未提交patch不得冒充commit。
2. `EvaluationDataset`、Version、Case、Run、Plan、CaseResult、MetricDefinition/Result、Comparison、Gate、BadCase/Event、Promotion、ReplayManifest和ArtifactRef均严格、版本化、有provenance/content hash/大小测试。
3. Dataset支持dev/locked_test/regression和human/confirmed/synthetic来源；Frozen Version不可原地修改。
4. Gold变化只创建新Dataset Version；系统输出、Trace、Legacy、LLM Judge不能自动写Gold。
5. Locked Test不进入fit、Prompt、权重或阈值选择，并有访问与泄漏测试。
6. 六类Adapter均至少在offline或deterministic模式可运行，严格repo/index/paper隔离且单Case失败隔离。
7. Index/Retrieval/Agent/Alignment/Answer/Observability指标都有版本、denominator、empty/incomplete策略和手算测试。
8. Retrieval报告Recall@1/5/10/20、MRR、nDCG、Graph Path、Empty/Fallback和Latency。
9. Agent报告Task/Route/Plan/Tool/Evidence/Citation/Recovery/Budget/Latency/Token。
10. Alignment报告Candidate/Pair/Exact Set/Selective/Coverage/Abstention/no-implementation/Evidence/Brier/ECE；无Gold时明确not_evaluable。
11. `ALIGNMENT_BENCHMARK_PENDING`被真实双标Gold关闭；若因授权未完成，状态继续显式保留且v1.9不得声称Alignment quality DoD完成。
12. Answer主指标基于人工/确定性Gold points和Citation事实；LLM Judge仅为optional辅助。
13. Observability报告Completeness/Integrity/Link/Redaction/Drop/Overhead；partial/unknown输入MetricResult为complete=false。
14. Comparison同时报告Overall和source/repo/pair/tag/type subgroup；不兼容Baseline不能自动Gate。
15. Hard Invariant能阻断跨repo、Invalid Tool、非法Citation、未知Candidate、Secret泄漏、Recorder不等价、Gold修改和未授权Live。
16. Quality/Performance Gate使用v1.9-a冻结的真实阈值和版本，不使用计划中的伪数字；incomplete为indeterminate并阻断promotion。
17. Bad Case有append-only事件、revision锁和完整open→closed/rejected生命周期。
18. 自动Root Cause只是建议；confirmed必须人工操作并关联Evidence。
19. fixed不等于verified；verified/closed必须关联后续compatible Evaluation Run。
20. Promotion创建新Dataset Version，保存bad_case/source trace/fix commit，不修改旧Frozen Gold。
21. Offline Replay无网络、无业务写入；Live Replay有permission/consent/budget/concurrency和固定版本。
22. Replay创建新run_id/trace_id并保留原Run，不覆盖结果、不写Gold、不切换生产active。
23. Evaluation Store独立migration/Lease/retry/idempotency/short transaction/retention，不修改业务Store/Trace/Checkpoint。
24. EvaluationRunCoordinator支持claim once、heartbeat、recovery、cancel、graceful shutdown、case/provider并发上限和progress。
25. Evaluation Trace使用新Trace/Link/ArtifactRef，原Trace只读；Evaluation故障不影响业务运行。
26. API默认关闭，统一Access Policy、幂等、分页、大小、mode权限和稳定错误码均有合同测试。
27. Dashboard可显示Run、Comparison、Gate、Bad Case、Trace Link、Dataset Version和Promotion，不成为Gold算法源。
28. CI deterministic regression suite无网络、无模型下载、无付费调用且可用非零退出码阻断回归。
29. Recorder/Evaluation On/Off时业务结果、Retrieval排序、Run/Checkpoint、Alignment Decision/Deployment和Trace隐私语义不变。
30. 完整后端测试、前端测试/build和`scripts/validate.sh`通过，真实Baseline/Gate/故障注入结果写入v1.9验收文档。
31. v1.4事实ID、v1.5 Retrieval、v1.6 Agent、v1.7 Alignment、v1.8 Observability以及旧Analysis/报告/前端保持兼容。

本文件只定义 v1.9 后续实施方案；本轮未实现 Evaluation Runner、Regression Gate、Bad Case Store、Replay、Evaluation SQLite/API/Dashboard或任何正式 v1.9 功能代码。
