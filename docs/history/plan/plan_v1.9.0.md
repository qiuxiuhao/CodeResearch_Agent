# CodeResearch Agent v1.9.0：Evaluation、Bad Case 与 Regression Loop 开发计划

状态：v1.8 正式基线冻结、评测资产审计完成、v1.9 开工前设计冻结

事实基线：

- 分支：`upgrade/v1.7-paper-code-alignment`
- Commit：`db6685a45baa5f75e4856cbc406e410ad313f332`
- Tag：`v1.8.0`（annotated tag；解引用后指向同一 Commit）
- 工作树状态：`CLEAN`（本计划修订开始前核验）

优先技术债：`ALIGNMENT_BENCHMARK_PENDING`
实施范围：v1.9.0-a 至 v1.9.0-f2

## 0. 开工前置条件

1. 正式 v1.8 Evaluation 基线固定为完整 Commit `db6685a45baa5f75e4856cbc406e410ad313f332`；`v1.8.0` 只作为可读 release 标签，身份判断始终使用完整 Commit SHA，不能只保存可移动分支名或 Tag 名。
2. 当前 Tag、HEAD 与干净工作树已经核验。正式 Baseline Run 必须基于该 Commit 或后续另行冻结的完整 Commit；带未提交 Patch 的 Run 只能是开发实验，`worktree_patch_hash` 不能替代正式 Commit，也不能晋升正式 Baseline。
3. Dataset provenance、Evaluation Subject、Run Fingerprint 必须记录实际 v1.8 Commit/Tag、依赖锁、Fixture、配置、Prompt、模型和 Provider revision。代码或任何有效配置变化后必须创建新的 `EvaluationSubject`，不得沿用旧 Subject ID。
4. 当前 Alignment 实际为 0 case/0 pair。`ALIGNMENT_BENCHMARK_PENDING` 是 v1.9-a 优先任务；在真实 Gold 冻结前，所有 Alignment Accuracy/F1/Calibration Gate 必须显示 `not_evaluable`，不得使用 Legacy、Scorer、LLM 或 Trace 输出填充。
5. Retrieval 40 case 和 Agent 30 case 都是 synthetic/contract fixture，不得描述成 5 个真实开源仓库的人工质量集。v1.9 必须保存其来源类型并与 human-authored 结果分组报告。
6. 自动 CI 只能运行 `offline_recompute` 与 `deterministic_fixture`，禁止网络、真实 Provider、模型下载、Gold 写回和业务状态修改。
7. Evaluation 必须是独立流程：

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

1. 统一Evaluation Subject、Dataset/Case/Version、Plan/Run/Result与Baseline Binding Schema。
2. Dataset Catalog、Frozen Gold、Fixture Binding、provenance与content hash。
3. Index/Retrieval/Agent/Alignment/Answer/Observability 六类 Adapter。
4. 版本化 Metric Engine 与整体/pair/repo/tag/type subgroup 报告。
5. Run Fingerprint/Environment/Comparison Scope、Baseline Binding与版本化CI/Release/Manual Regression Gate。
6. Bad Case Analyzer、fingerprint/Occurrence、append-only生命周期、Case-level Verification与人工Triage。
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

新增 `backend/app/evaluation/schemas.py`。全部模型使用 Pydantic v2、`extra="forbid"`、可变字段 `default_factory`、受限 `JsonValue`、UTC 时间、显式 schema/version/provenance/content hash 和大小限制。以下联合均使用 `component` 判别，不允许字典形状猜测或 `...` 占位。

### 6.1 基础类型、Subject 与 Provenance

```python
DatasetSplit = Literal["dev", "locked_test", "regression"]
DatasetSource = Literal["human_authored", "confirmed_bad_case", "synthetic_fixture"]
EvaluationMode = Literal["offline_recompute", "deterministic_fixture", "live_experiment"]
EvaluationComponent = Literal[
    "index", "retrieval", "agent", "alignment", "answer", "observability",
]

class EvaluationSubject(StrictModel):
    schema_version: str
    subject_id: str
    subject_type: Literal[
        "code_commit", "worktree_patch", "configuration",
        "prompt_profile", "model_profile", "combined",
    ]
    code_commit_sha: str
    code_tag: str | None
    worktree_patch_hash: str | None
    config_hash: str
    prompt_profile_ids: dict[str, str]
    model_profile_ids: dict[str, str]
    provider_revisions: dict[str, str]
    dependency_lock_hash: str
    subject_hash: str
    created_at: datetime

class EvaluationProvenance(StrictModel):
    schema_version: str
    subject_id: str
    dataset_version_id: str | None
    fixture_version: str | None
    repo_id: str | None
    reference_index_version_id: str | None
    candidate_index_version_id: str | None
    paper_id: str | None
    adapter_profile_hash: str | None
    metric_definition_hash: str | None
    created_at: datetime
```

正式 Baseline Subject 只能是干净 `code_commit`，或所有配置、Prompt、模型、Provider revision 和依赖锁都完整固定的 `combined`；两者的 `worktree_patch_hash` 必须为空。开发实验可以使用 `worktree_patch`，但不得晋升正式 Baseline。Subject 创建后不可修改；Commit、依赖、配置、Prompt、模型或 Provider revision 任一变化都创建新 Subject。`subject_hash` 覆盖全部有效输出因素；Tag 只作可读标签，完整 Commit SHA 才是身份。

### 6.2 Dataset、Fixture 与严格 Component 合同

```python
class EvaluationDataset(StrictModel):
    schema_version: str
    dataset_id: str
    dataset_family_id: str
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
    gold_hash: str
    fixture_hash: str
    content_hash: str
    annotation_policy_version: str
    authorization_scope_hash: str
    provenance: EvaluationProvenance
    created_at: datetime
    frozen_at: datetime | None

class EvaluationFixtureBinding(StrictModel):
    schema_version: str
    repository_fixture_id: str
    repository_content_hash: str
    paper_fixture_id: str | None
    paper_content_hash: str | None
    reference_index_version_id: str | None
    reference_index_manifest_hash: str | None
    candidate_index_namespace: str | None
    fixture_version: str
    artifact_ref_ids: list[str]

class IndexEvaluationInput(StrictModel):
    component: Literal["index"]
    repository_artifact_ref_ids: list[str]
    build_profile_id: str
    candidate_namespace_policy: Literal["temporary_database", "isolated_namespace"]

class RetrievalEvaluationInput(StrictModel):
    component: Literal["retrieval"]
    query_artifact_ref_ids: list[str]
    retrieval_profile_id: str
    top_k: int
    filters: dict[str, JsonValue]

class AgentEvaluationInput(StrictModel):
    component: Literal["agent"]
    task_artifact_ref_ids: list[str]
    run_profile_id: str
    budget_profile_id: str
    fault_profile_id: str | None

class AlignmentEvaluationInput(StrictModel):
    component: Literal["alignment"]
    paper_artifact_ref_ids: list[str]
    profile_ids: list[str]
    alignment_model_profile_id: str
    deployment_id: str | None

class AnswerEvaluationInput(StrictModel):
    component: Literal["answer"]
    answer_artifact_ref_ids: list[str]
    context_artifact_ref_ids: list[str]
    answer_profile_id: str

class ObservabilityEvaluationInput(StrictModel):
    component: Literal["observability"]
    trace_artifact_ref_ids: list[str]
    recorder_profile_id: str
    operation_taxonomy_version: str

EvaluationInput = Annotated[
    IndexEvaluationInput | RetrievalEvaluationInput | AgentEvaluationInput |
    AlignmentEvaluationInput | AnswerEvaluationInput | ObservabilityEvaluationInput,
    Field(discriminator="component"),
]

class IndexGold(StrictModel):
    component: Literal["index"]
    required_entity_ids: list[str]
    required_edge_ids: list[str]
    required_evidence_ids: list[str]
    required_chunk_ids: list[str]
    allowed_unresolved_symbols: list[str]
    expected_manifest_fields: dict[str, JsonValue]
    expected_id_stability: dict[str, str]

class RetrievalGold(StrictModel):
    component: Literal["retrieval"]
    required_entity_ids: list[str]
    required_chunk_ids: list[str]
    relevance_by_entity: dict[str, float]
    relevance_by_chunk: dict[str, float]
    required_paths: list[list[str]]
    required_edge_types: list[str]
    allowed_unresolved: list[str]
    max_empty_results: int

class AgentGold(StrictModel):
    component: Literal["agent"]
    expected_route: str
    required_tools: list[str]
    optional_tools: list[str]
    forbidden_tools: list[str]
    allowed_tool_orders: list[list[str]]
    required_evidence_ids: list[str]
    required_edge_ids: list[str]
    expected_sufficient: bool
    expected_terminal_status: str
    max_tool_calls: int
    max_replans: int
    expected_partial_reason_codes: list[str]

class AlignmentGoldSelection(StrictModel):
    code_entity_id: str
    relation_type: str

class AlignmentGold(StrictModel):
    component: Literal["alignment"]
    profile_id: str
    gold_selections: list[AlignmentGoldSelection]
    acceptable_alternative_sets: list[list[AlignmentGoldSelection]]
    alignable: bool
    no_implementation_expected: bool
    required_paper_evidence_ids: list[str]
    required_code_evidence_ids: list[str]
    relation_types: list[str]

class AnswerGold(StrictModel):
    component: Literal["answer"]
    required_answer_points: list[str]
    optional_answer_points: list[str]
    forbidden_claims: list[str]
    required_evidence_ids: list[str]
    allowed_citation_sets: list[list[str]]
    required_claim_relations: list[str]
    evidence_only_expected: bool
    partial_expected: bool

class ObservabilityGold(StrictModel):
    component: Literal["observability"]
    required_operations: list[str]
    required_parent_child_edges: list[tuple[str, str]]
    required_links: list[dict[str, str]]
    forbidden_attributes: list[str]
    required_integrity_state: Literal["complete", "partial", "unknown"]
    allowed_integrity_flags: list[str]
    max_drop_count: int
    max_missing_span_count: int

EvaluationGold = Annotated[
    IndexGold | RetrievalGold | AgentGold | AlignmentGold |
    AnswerGold | ObservabilityGold,
    Field(discriminator="component"),
]

class IndexOutcome(StrictModel):
    component: Literal["index"]
    candidate_index_version_id: str
    entity_ids: list[str]
    edge_ids: list[str]
    evidence_ids: list[str]
    chunk_ids: list[str]
    unresolved_symbols: list[str]
    manifest_hash: str

class RetrievalOutcome(StrictModel):
    component: Literal["retrieval"]
    ranked_entity_ids: list[str]
    ranked_chunk_ids: list[str]
    graph_paths: list[list[str]]
    channel_status: dict[str, str]
    fallback_reason_codes: list[str]

class AgentOutcome(StrictModel):
    component: Literal["agent"]
    route: str
    plan_steps: list[str]
    tool_calls: list[dict[str, JsonValue]]
    evidence_ids: list[str]
    edge_ids: list[str]
    sufficient: bool
    terminal_status: str
    partial_reason_codes: list[str]

class AlignmentOutcome(StrictModel):
    component: Literal["alignment"]
    profile_id: str
    candidate_ids: list[str]
    selections: list[AlignmentGoldSelection]
    decision_status: str
    paper_evidence_ids: list[str]
    code_evidence_ids: list[str]
    candidate_probabilities: dict[str, float]

class AnswerOutcome(StrictModel):
    component: Literal["answer"]
    answer_point_ids: list[str]
    claims: list[dict[str, JsonValue]]
    citation_ids: list[str]
    evidence_ids: list[str]
    partial: bool

class ObservabilityOutcome(StrictModel):
    component: Literal["observability"]
    operation_names: list[str]
    parent_child_edges: list[tuple[str, str]]
    links: list[dict[str, str]]
    observed_attribute_keys: list[str]
    completeness: Literal["complete", "partial", "unknown"]
    integrity_flags: list[str]
    drop_count: int
    missing_span_count: int

EvaluationOutcome = Annotated[
    IndexOutcome | RetrievalOutcome | AgentOutcome | AlignmentOutcome |
    AnswerOutcome | ObservabilityOutcome,
    Field(discriminator="component"),
]

class EvaluationCase(StrictModel):
    schema_version: str
    case_id: str
    stable_case_family_id: str
    dataset_version_id: str
    split: DatasetSplit
    source: DatasetSource
    component: EvaluationComponent
    fixture: EvaluationFixtureBinding
    repo_id: str
    reference_index_version_id: str | None
    paper_id: str | None
    input: EvaluationInput
    input_artifact_ref_ids: list[str]
    gold: EvaluationGold
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str]
    annotator_scope_hashes: list[str]
    adjudication_status: Literal[
        "not_required", "pending", "agreed", "adjudicated", "disputed",
    ]
    provenance: EvaluationProvenance
    content_hash: str
```

Reference Index 只表示 Dataset Gold/参考事实。Index Adapter 必须在临时数据库或隔离 namespace 为 Candidate Subject 构建新 Index，Candidate ID 不回写 Frozen Dataset、不切换生产 active version。Retrieval/Agent Case 使用冻结的 Reference Index Fixture，不得静默跟随生产 active Index；Fixture 或 manifest 改变必须新建 Dataset Version。

### 6.3 Environment、Plan、Fingerprint、Run 与 Baseline Binding

```python
class ExecutionEnvironment(StrictModel):
    schema_version: str
    environment_id: str
    python_version: str
    dependency_lock_hash: str
    os_name: str
    os_version: str
    cpu_profile: str
    gpu_profile: str | None
    memory_profile: str | None
    provider_region: str | None
    cache_profile: Literal["cold", "warm", "mixed", "not_applicable"]
    case_concurrency: int
    provider_concurrency: int
    environment_hash: str

class EvaluationRunFingerprint(StrictModel):
    schema_version: str
    dataset_version_id: str
    case_set_hash: str
    subject_id: str
    metric_definition_hash: str
    adapter_profile_hash: str
    fixture_hash: str
    execution_mode: EvaluationMode
    environment_hash: str
    random_seed: int
    run_fingerprint_hash: str

class LiveTrialSpec(StrictModel):
    trial_group_id: str
    repeat_count: int
    temperature: float | None
    seed: int | None
    seed_supported: bool

class EvaluationPlan(StrictModel):
    schema_version: str
    plan_id: str
    dataset_version_id: str
    subject_id: str
    mode: EvaluationMode
    components: list[EvaluationComponent]
    adapter_versions: dict[str, str]
    metric_definition_ids: list[str]
    case_ids: list[str]
    baseline_binding_id: str | None
    gate_config_version: str | None
    frozen_config_hash: str
    case_concurrency: int
    provider_concurrency: int
    provider_budget: ProviderBudget | None
    external_model_consent: bool
    random_seed: int
    live_trial: LiveTrialSpec | None
    provenance: EvaluationProvenance

class EvaluationRun(StrictModel):
    schema_version: str
    run_id: str
    plan_id: str
    dataset_version_id: str
    subject_id: str
    mode: EvaluationMode
    status: Literal[
        "queued", "preparing", "running", "aggregating", "comparing",
        "completed", "partial", "failed", "cancelled",
    ]
    run_fingerprint: EvaluationRunFingerprint
    environment_id: str
    trial_group_id: str | None
    repeat_index: int | None
    repeat_count: int | None
    temperature: float | None
    seed: int | None
    attempt_number: int
    retry_of_run_id: str | None
    cancel_requested: bool
    lease_owner_hash: str | None
    case_counts: dict[str, int]
    complete: bool
    incomplete_reason_codes: list[str]
    error_code: str | None
    provenance: EvaluationProvenance
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

class EvaluationBaselineBinding(StrictModel):
    schema_version: str
    baseline_binding_id: str
    dataset_version_id: str
    component: EvaluationComponent
    evaluation_mode: EvaluationMode
    gate_config_version: str
    baseline_run_id: str
    subject_id: str
    status: Literal["active", "superseded", "retired"]
    promoted_by_scope_hash: str
    promotion_reason_code: str
    created_at: datetime
    promoted_at: datetime
```

`EvaluationRun` 是一次不可变评测执行；终态后不得因 Baseline 选择而 UPDATE。`EvaluationBaselineBinding` 才表示某 Dataset/Component/Mode/Gate Config 范围的当前 Baseline。只允许完整 `completed` Run 晋升；`partial|failed|cancelled` 禁止晋升。每个范围最多一个 active Binding，新 Binding 激活与旧 Binding supersede在同一短事务中完成，且不修改源 Run。Promotion 是显式权限操作；synthetic 与 human-authored 不得隐式混为一个 Baseline。

### 6.4 Case Result、Metric、Comparison 与 Gate

```python
class CaseResult(StrictModel):
    schema_version: str
    result_id: str
    evaluation_run_id: str
    case_id: str
    component: EvaluationComponent
    execution_status: Literal[
        "queued", "running", "completed", "error", "skipped", "cancelled",
    ]
    evaluation_outcome: Literal[
        "passed", "failed", "not_evaluable", "indeterminate",
    ] | None
    complete: bool
    incomplete_reason_codes: list[str]
    execution_error_code: str | None
    quality_failure_codes: list[str]
    outcome: EvaluationOutcome | None
    business_run_id: str | None
    trace_id: str | None
    output_artifact_refs: list["EvaluationArtifactRef"]
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

class ComparisonScope(StrictModel):
    schema_version: str
    common_case_ids: list[str]
    excluded_baseline_case_ids: list[str]
    excluded_candidate_case_ids: list[str]
    comparable_metric_definition_ids: list[str]
    incompatible_metric_definition_ids: list[str]
    compatibility: Literal["compatible", "partially_compatible", "incompatible"]
    incompatibility_reasons: list[str]

class RegressionComparison(StrictModel):
    schema_version: str
    comparison_id: str
    baseline_binding_id: str
    baseline_run_id: str
    candidate_run_id: str
    baseline_subject_id: str
    candidate_subject_id: str
    scope: ComparisonScope
    metric_deltas: list[MetricDelta]
    subgroup_deltas: list[MetricDelta]
    status: Literal["pending", "ready", "invalid"]
    created_at: datetime

class GateRule(StrictModel):
    rule_id: str
    metric_definition_id: str
    scope: Literal["overall", "split", "source", "repo", "pair", "tag", "type"]
    subgroup_filter: dict[str, str]
    comparison: Literal[
        "equal_zero", "min_value", "max_value",
        "max_absolute_drop", "max_relative_drop",
    ]
    threshold: float
    min_sample_count: int
    incomplete_policy: Literal["block", "warning", "ignore"]
    severity: Literal["warning", "block"]

class RegressionGateConfig(StrictModel):
    schema_version: str
    gate_config_version: str
    profile_type: Literal["ci", "release", "manual"]
    hard_rules: list[GateRule]
    quality_rules: list[GateRule]
    performance_rules: list[GateRule]
    critical_subgroups: list[dict[str, str]]
    minimum_live_repeat_count: int | None
    config_hash: str
    created_at: datetime

class GateRuleResult(StrictModel):
    rule_id: str
    verdict: Literal["passed", "warning", "blocked", "indeterminate"]
    numerator: float | None
    denominator: float | None
    sample_count: int
    baseline_value: float | None
    candidate_value: float | None
    absolute_delta: float | None
    relative_delta: float | None
    evidence_artifact_ref_ids: list[str]
    reason_codes: list[str]

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
```

Provider timeout是 `execution_status=error`，不是质量失败；业务成功但 Gold 不满足是 `completed+failed`；没有 Gold 是 `completed+not_evaluable`；输入、Trace 或 Artifact 不完整且无法下结论是 `indeterminate`。Bad Case Analyzer必须分别处理 `execution_error|quality_failure|gold_invalid|not_evaluable|telemetry_incomplete`。

Comparison 兼容性由 Dataset Version、Case Set、Gold/Fixture hash、Metric Definition、Adapter major version、Mode、Subject中的 Model/Prompt/Config、Environment、Cache、Concurrency和Hardware共同决定。Quality 可在严格共同 Case 范围部分比较；Performance只有环境、cache、并发和硬件兼容时才可 Gate。`partially_compatible`只展示共同范围；`incompatible`禁止自动 Gate，并持久化全部排除 Case/Metric。

### 6.5 Bad Case、Promotion、Verification 与 Replay

```python
class BadCase(StrictModel):
    schema_version: str
    bad_case_id: str
    fingerprint: str
    source_result_id: str
    source_evaluation_run_id: str
    source_trace_id: str | None
    stable_case_family_id: str
    case_id: str
    component: EvaluationComponent
    symptom: BadCaseSymptom
    suggested_root_causes: list[RootCauseSuggestion]
    confirmed_root_cause: BadCaseRootCause | None
    status: Literal[
        "open", "triaged", "confirmed", "fixing", "fixed",
        "verified", "closed", "rejected",
    ]
    revision: int
    severity: Literal["low", "medium", "high", "critical"]
    evidence_ref_ids: list[str]
    fix_reference: "FixReference | None"
    verification_id: str | None
    first_seen_run_id: str
    last_seen_run_id: str
    occurrence_count: int
    created_at: datetime
    updated_at: datetime

class BadCaseOccurrence(StrictModel):
    schema_version: str
    occurrence_id: str
    bad_case_id: str
    evaluation_run_id: str
    case_result_id: str
    trace_id: str | None
    subject_id: str
    observed_at: datetime

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

class FixReference(StrictModel):
    schema_version: str
    fix_type: Literal[
        "code_commit", "configuration", "prompt_profile",
        "model_profile", "dataset_fix",
    ]
    reference_id: str
    content_hash: str

class RegressionCasePromotion(StrictModel):
    schema_version: str
    promotion_id: str
    bad_case_id: str
    source_dataset_version_id: str
    target_dataset_version_id: str
    new_case_id: str
    source_trace_id: str | None
    pre_fix_reproduction_result_id: str | None
    reproduction_status: Literal["pending", "reproduced", "not_reproducible", "rejected"]
    fix_reference: FixReference | None
    gold_review_status: Literal["pending", "approved", "rejected"]
    fixture_minimization_status: Literal["pending", "complete", "not_possible"]
    created_at: datetime

class BadCaseVerification(StrictModel):
    schema_version: str
    verification_id: str
    bad_case_id: str
    verification_run_id: str
    verification_case_result_id: str
    relevant_metric_result_ids: list[str]
    required_gate_rule_ids: list[str]
    case_passed: bool
    relevant_rules_passed: bool
    regression_case_passed: bool
    verified_at: datetime

class ReplayManifest(StrictModel):
    schema_version: str
    replay_manifest_id: str
    replay_type: Literal["analysis", "offline", "live"]
    source_evaluation_run_id: str
    source_business_run_id: str | None
    source_subject_id: str
    replay_subject_id: str
    source_trace_id: str | None
    source_checkpoint_id: str | None
    required_artifact_ref_ids: list[str]
    readiness: Literal["ready", "not_ready", "consent_required", "artifact_missing"]
    reason_codes: list[str]
    external_model_consent: bool
    budget: ProviderBudget | None
    trial_spec: LiveTrialSpec | None
    execution_requested: bool
    content_hash: str
```

Bad Case fingerprint固定为 dataset family + stable case identity + component + symptom + normalized failure code；Root Cause建议不进入fingerprint，Analyzer升级不得制造新Bad Case。相同fingerprint追加append-only Occurrence。Closed Case再次发生时追加recurrence Event并回到`open`，保留旧verification；不同Gold Version是否归并由`stable_case_family_id`显式决定。

正确修复顺序是：confirmed → 创建Regression Case → 修复前稳定复现 → fixing → 关联FixReference → fixed → 新版本Case级验证 → verified。Promotion时FixReference可为空；进入fixed必须存在。非代码修复不得伪装Commit；`dataset_fix`只表示原Gold/Dataset错误，不能计为模型质量提升。无法稳定复现的Promotion保持pending或rejected。

Bad Case进入verified只要求对应Case与Regression Case通过、相关Hard Rule通过且数据/指标兼容，不要求候选版本所有无关Gate都通过。Closed仍要求confirmed root cause、FixReference、BadCaseVerification、verified Event和Evidence。

### 6.6 Artifact、Resolver 与业务等价合同

```python
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
    storage_kind: Literal[
        "evaluation_store", "business_store", "trace_store", "checkpoint_store",
        "fixture_catalog", "filesystem_fixture",
    ]
    storage_locator: str
    media_type: str
    size_bytes: int | None
    redaction_policy: str
    availability_status: Literal["available", "missing", "expired", "access_denied"]

class BusinessEquivalenceContract(StrictModel):
    schema_version: str
    contract_id: str
    component: EvaluationComponent
    required_equal_fields: list[str]
    ignored_fields: list[str]
    order_insensitive_fields: list[str]
    float_tolerances: dict[str, float]
    normalizer_version: str
    config_hash: str

class EvaluationArtifactResolver(Protocol):
    def resolve(
        self,
        artifact_ref: EvaluationArtifactRef,
        access_context: EvaluationAccessContext,
    ) -> ResolvedArtifact: ...
```

`storage_locator`是受控locator，不是任意绝对/相对文件路径；只有Resolver可以解析，并在每次读取时重新授权、校验hash/size/media type。API不返回敏感内部绝对路径。Hash不匹配时CaseResult必须`complete=false`且`indeterminate`；Offline Replay先验证全部Artifact availability/hash。

Recorder On/Off使用版本化BusinessEquivalenceContract做规范化比较：忽略trace/request/time/latency/telemetry计数、内部Span/Event ID和无业务语义执行ID；严格比较Retrieval排序/Candidate ID、Agent route/plan/tool/evidence/terminal、Answer/Claim/Citation、Alignment Selection/Decision和Business Store状态。浮点容差必须版本化，不能用“完整JSON不同”或宽泛忽略字段判断。

不得在 `JsonValue` 中塞完整 State、任意对象、Prompt、模型响应或源码。建议硬限制：Case input/gold 各64KiB、CaseResult 128KiB、每Run 10,000 case、每Case 200 ArtifactRef、tags 50、错误/原因码100；大结果通过受控ArtifactRef分页读取。

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

首个v1.9 Dataset Version的provenance必须引用正式v1.8 Subject：Commit `db6685a45baa5f75e4856cbc406e410ad313f332`、Tag `v1.8.0`。后续代码、配置、Prompt或模型变化创建新EvaluationSubject；Dataset本身不因被测Subject变化而改写，但每个Plan/Run必须显式固定`subject_id`。

Locked Test 的访问和结果读取需要独立 scope；Runner 只能按 Plan 中冻结的 Case ID读取，不能把 Locked 原文发送给未授权 Provider。Live 结果不会自动替换 Frozen Baseline。

### 7.3 Gold 规则

- Gold 不得由被评测系统、Legacy Alignment、当前 Scorer、LLM Judge 或 Trace 自动生成。
- LLM 只能辅助定位 Evidence/候选；最终 Gold 必须人工确认或来自可证明的 deterministic fixture。
- 每个 Case 使用`EvaluationFixtureBinding`固定repo/paper/reference index与content hash；Fixture变化必须新建Dataset Version。
- `reference_index_version_id`只用于Gold/参考事实；Candidate Subject构建出的Index进入隔离临时DB/namespace，不能写回Dataset或切换生产active version。
- Retrieval/Agent Case读取被冻结的Index Fixture，不得把“当前生产active index”当隐式输入。
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

真实 Provider/模型的受控实验，必须同时满足：显式mode permission、external consent、固定Subject/Provider/model/revision/Prompt、版本化预算、独立Run/Trace/Store namespace、case/provider concurrency cap和审计。

Live使用`trial_group_id + repeat_index + repeat_count + temperature + seed`。每个Trial创建独立Evaluation Run、业务Run和Trace，结果互不覆盖；不支持seed的Provider必须记录`seed_supported=false`。报告同时给出均值、方差、成功率与Provider Failure Rate。单次Live Trial不能晋升正式Locked Baseline；Promotion必须满足Gate Config冻结的最小重复次数、完整性和兼容性。Live失败不修改Gold或Baseline Binding。

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

Adapter不拥有Gold，不修改Dataset，不直接决定Gate。Provider timeout等执行异常转换为`execution_status=error`；执行完成但不符合Gold转换为`completed+evaluation_outcome=failed`；缺Gold为`not_evaluable`；输入/Trace/Artifact不完整且不能判断为`indeterminate`。任何单Case异常不得导致其他Case丢失。

所有Adapter通过`EvaluationArtifactResolver`读取Artifact并重新授权/校验hash；不得直接拼接文件路径。Index Adapter在隔离namespace构建Candidate Index。Recorder On/Off对比必须使用对应`BusinessEquivalenceContract`规范化动态telemetry字段，并严格比较业务排序、决策、状态和Artifact。

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

Comparison先解析`EvaluationBaselineBinding`，再校验Baseline/Candidate Run Fingerprint与`ComparisonScope`。兼容性至少覆盖Dataset Version、Case Set、Gold Hash、Fixture Hash、Metric Definition、Adapter major version、Evaluation Mode、Subject中的Model/Prompt/Config、Execution Environment、Cache Profile、Concurrency与Hardware。

- Quality允许在严格共同Case范围内`partially_compatible`比较，但必须保存双方排除Case和不兼容Metric，报告不得外推到全Dataset。
- Performance只有environment/cache/concurrency/hardware兼容时才能Gate；否则只能并排展示。
- `incompatible`不得自动Gate或晋升Baseline。
- Baseline选择通过独立Binding完成；Run终态不可因Promotion改变。

`RegressionGateConfig`必须在Run读取Case结果前冻结，关键subgroup不能看结果后追加来阻断或放行。Rule、threshold、min sample、incomplete policy、severity或critical subgroup任一变化都创建新的`gate_config_version/config_hash`，旧Config不可覆盖。每条Rule分别保存numerator、denominator、sample count、Baseline/Candidate值、absolute/relative delta与Artifact依据。相对变化在Baseline为0时：若Candidate也为0则delta=0；若Candidate非0则relative delta为null并按Rule的absolute/equal-zero语义与incomplete policy处理，禁止除零或伪造无穷改进。

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

Hard input缺失时Rule为`indeterminate`；Release Profile必须block，CI Profile按该Rule冻结的`incomplete_policy`处理，不能当passed。

### 11.2 Quality Gate

按Metric direction比较absolute delta、relative delta和subgroup delta。Overall改善不能覆盖任一预先冻结的关键repo/tag/relation/query type退化。小于`min_sample_count`时按Rule的incomplete policy处理。Warning Rule只告警，Block Rule才阻断。阈值必须在v1.9-a用真实Baseline、样本量与方差冻结并升级gate config version；本计划不预写最终数值。

### 11.3 Performance Gate

比较P50/P95 latency、Token、tool calls、replans、provider calls、known cost和Trace overhead。冷/热cache、硬件、并发或mode不同的结果不可直接Gate。性能缺样本或telemetry incomplete时按Rule返回warning/block/indeterminate。

### 11.4 CI、Release 与 Manual Profile

- `ci`：只含Hard Invariant、小型deterministic regression、稳定可计算组件指标、Dataset/Gold Hash、无网络和无业务写入检查。小Fixture无法计算Calibration/P95时，只按CI Rule自己的incomplete policy处理，不能永久阻断所有PR。
- `release`：包含完整human-authored Dataset、Alignment Gold、Answer Gold、关键质量subgroup、性能指标和Gate要求的重复Live结果；Release Hard Invariant indeterminate必须阻断。
- `manual`：用于受权诊断/实验，仍须版本化Rule、Subject、Dataset和Comparison，不得绕过Hard Invariant后伪装Release结论。

CLI必须显式选择`gate_config_version`及其profile；不同profile结果不可互换。

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

Analyzer只能依据CaseResult、Metric、Trace metadata、ArtifactRef和known failure code输出带Evidence的`RootCauseSuggestion(confidence, reason_codes, evidence_refs)`。它必须先把触发类型归类为`execution_error|quality_failure|gold_invalid|not_evaluable|telemetry_incomplete`，不得把Provider timeout算成质量失败，也不得从not-evaluable样本制造wrong-answer Bad Case。它不得自动设置`confirmed_root_cause`、修改代码/Prompt/Gold或推进到fixed/closed。

Bad Case fingerprint由dataset family、stable case identity、component、symptom和normalized failure code生成；Root Cause建议不参与。相同fingerprint再次出现只追加`BadCaseOccurrence`并更新派生first/last/count。事件与Occurrence均append-only。Closed Case复发时追加`recurrence` Event并重新open，旧Fix/Verification历史保留；跨Gold Version是否去重由stable case family ID明确控制。

## 13. Bad Case 生命周期

```text
open → triaged → confirmed → fixing → fixed → verified → closed
  └──────────────────────────────────────────────────→ rejected
```

- 每次状态变化追加 `BadCaseEvent`，不 UPDATE/删除历史事件。
- `based_on_revision` 乐观锁；旧 revision 返回 409。
- `confirmed`后可以先Promotion Regression Case，不要求Fix已经存在。
- 进入`fixing`前必须有能稳定复现失败的Regression Case；无法复现时Promotion保持pending/rejected。
- `fixed`必须关联typed `FixReference`，绝不等于指标已恢复；configuration/prompt/model修复不得伪装Git Commit。
- `verified`必须关联`BadCaseVerification`：对应Case通过、匹配Regression Case通过、相关Hard Rule通过且数据/指标兼容；不要求整个候选版本的无关Quality Gate全部通过。
- `closed`必须有confirmed root cause、FixReference、BadCaseVerification、verified event和相关Evidence。
- rejected 保存原因，不删除原 Case/Trace。
- Trace、Evidence与FixReference只保存ID/hash/ref；不复制Prompt、源码或Checkpoint。

## 14. Regression Case Promotion

```text
Bad Case confirmed
→ Gold合法性与授权审核
→ 最小化deterministic Fixture
→ 创建Regression Case到新draft Dataset Version
→ 在修复前稳定重现原失败
→ 冻结新Dataset Version
→ fixing并关联FixReference
→ 新Subject评测
→ Case-level verified
```

Promotion保存原`bad_case_id`、source result/trace、原/new Dataset Version、Gold reviewer、fixture hash和pre-fix reproduction result。Promotion时FixReference可以为空；进入fixed才强制存在。`dataset_fix`只处理Gold/Dataset错误，其改善从模型质量趋势中排除。旧Frozen Dataset不变；不能稳定复现、依赖随机Provider输出或Gold有争议的Case保持pending/rejected。

## 15. Replay 边界

### 15.1 Replay Analysis

只读取Trace/Run/Metric/ArtifactRef重建时间线和比较，不执行Graph、Tool、Provider或业务写入。Analysis固定source/replay Subject身份，但不生成新业务Run。

### 15.2 Offline Replay

通过`EvaluationArtifactResolver`验证冻结Artifact availability/hash后，使用Fake/Mock、临时DB与固定seed重新计算组件输出。必须无网络、无付费、无业务状态修改；输出新Evaluation CaseResult/Trace，不覆盖原结果。任一Artifact缺失、过期、拒绝访问或hash不匹配均not-ready/indeterminate。

### 15.3 Live Replay

从原输入或受支持Checkpoint创建新的隔离业务Run。必须显式consent、固定Replay Subject/Provider/model/revision/Prompt、固定预算、新`run_id`、新`trace_id`，并用`replay_of` Link/ArtifactRef关联原Run。每个repeat是独立Trial，保存temperature/seed支持情况，输出均值、方差、成功率和Provider Failure Rate。保留原Run，不写Gold、不切换生产active Deployment。

LangGraph 从 Checkpoint 后恢复会重新执行后续 LLM/API/Interrupt，是实际执行而非只读调试；未授权、serializer不兼容、Artifact缺失或版本不一致时 ReplayManifest必须 `not_ready`。

## 16. Evaluation Store

使用独立 `data/evaluation.sqlite3`，不修改 structured index、Research、Alignment、Observability 或 Checkpoint DB。至少包含：

```text
evaluation_datasets
evaluation_dataset_versions
evaluation_cases
evaluation_subjects
evaluation_fixture_bindings
evaluation_execution_environments
evaluation_runs
evaluation_run_leases
evaluation_plans
evaluation_case_results
evaluation_metric_definitions
evaluation_metric_results
evaluation_comparisons
evaluation_baseline_bindings
regression_gate_configs
regression_gates
bad_cases
bad_case_occurrences
bad_case_events
bad_case_verifications
bad_case_evidence_refs
regression_case_promotions
evaluation_replay_manifests
evaluation_artifact_refs
evaluation_idempotency_keys
```

规则：

- 编号 migration、`PRAGMA user_version`、WAL、foreign keys、busy timeout和短事务。
- Frozen Dataset/Case和EvaluationSubject由trigger/service guard禁止UPDATE/DELETE；新Dataset Version通过复制引用+新增变更构建。
- Run状态只表示执行：`queued → preparing → running → aggregating → comparing → completed|partial`，任一执行阶段可到failed/cancelled。终态Run不可变，不存在Run级active/superseded。
- Baseline选择写`evaluation_baseline_bindings`；只绑定完整completed Run，并在同一短事务激活新Binding、supersede旧Binding，不UPDATE源Run。
- failed/cancelled同输入允许新attempt并保留retry chain；幂等复用使用Run Fingerprint，不能只比较dataset/config/code三个散列。
- CaseResult分阶段写入，execution status与quality outcome分列；单Case失败不回滚其他Case。completed/partial Run都可查，但只有完整completed可Promotion Baseline。
- BadCase event/occurrence/verification均append-only，event sequence与revision在短事务分配；相同fingerprint追加Occurrence。
- Artifact locator只能由Resolver生成/解析；Store不接受任意文件路径。Candidate Index namespace与production active严格隔离。
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
→ completed / partial
```

Coordinator负责heartbeat、lease expiry recovery、cancel、graceful shutdown、attempt retry、case isolation、progress和late result token校验。默认case concurrency有限；live provider concurrency更低且由统一Budget/Consent/Trial repeat控制。取消只阻止新Case并在安全边界停止，已完成CaseResult保留；任何终态不可取消。Baseline Promotion不属于Coordinator执行状态机，由独立有权Service创建Binding。

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
POST /evaluations/baselines
GET  /evaluations/baselines
GET  /evaluations/subjects/{subject_id}

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
- Run创建请求必须引用不可变`subject_id`；正式Baseline Promotion拒绝worktree Subject、partial Run、不足repeat的Live Trial或不兼容Comparison。
- Baseline Promotion必须引用`baseline_binding_id`范围和`gate_config_version`，由admin/release权限显式执行；原Run响应保持不变。
- Bad Case `mark-fixed`接受typed FixReference；`verify`接受Case-level verification result与相关Rule，不能用“整个Gate passed”代替。
- Artifact读取通过Resolver并重新授权，API不返回敏感绝对路径或未经Redaction的locator。
- Locked Test、Gold、diagnostic Trace和Checkpoint分别做权限检查。
- 稳定错误码至少包括`evaluation_disabled`、`evaluation_api_disabled`、`evaluation_live_disabled`、`dataset_not_frozen`、`dataset_version_conflict`、`gold_invalid`、`evaluation_subject_not_found`、`formal_subject_required`、`evaluation_run_not_found`、`evaluation_busy`、`evaluation_cancel_not_allowed`、`baseline_run_incomplete`、`comparison_incompatible`、`gate_indeterminate`、`bad_case_conflict`、`promotion_not_ready`、`replay_not_ready`、`artifact_unavailable`、`artifact_hash_mismatch`、`live_consent_required`、`live_repeat_insufficient`、`evaluation_response_too_large`。

## 20. 最小前端

- Evaluation Dashboard：Run、Subject、mode、dataset version、execution status、progress、quality outcome与performance summary。
- Baseline Comparison：Baseline Binding、双方Subject/Fingerprint/Environment、共同Case、排除Case、absolute/relative delta、overall/subgroup、compatibility与incomplete。
- Regression Gate：明确CI/Release/Manual Profile及Hard/Quality/Performance规则，显示每条Rule的numerator/denominator/sample与warning/block原因。
- Bad Case List/Detail：fingerprint、occurrence、recurrence、symptom、suggestion、人工root cause、events、Trace/Evidence/FixReference/Case-level Verification。
- Dataset Version View：split/source/count/hash/frozen/provenance；Gold内容按权限展示。
- Promotion Flow：Gold审核、fixture最小化、修复前复现、新Version preview与后续FixReference，不能直接修改Frozen Version。
- Trace Link：跳转v1.8 Explorer，不内联禁止内容。

不实现完整标注平台；第一版Gold编辑/双标可以通过版本化JSONL+validator+review manifest完成，前端只展示和执行受控状态操作。

## 21. CI Regression Command

新增建议入口：

```bash
python scripts/evaluate_regression.py \
  --mode deterministic_fixture \
  --dataset-version <frozen-version> \
  --baseline-binding <baseline-binding-id> \
  --gate-config <ci-gate-config-version> \
  --output <artifact-path>
```

CLI必须显式选择带`profile_type=ci|release|manual`的Gate Config，不能从环境隐式选择。CI只使用regression +小型synthetic locked subset、Mock/Fake、临时Store和固定seed；不得下载模型或访问网络。是否将indeterminate转为非零由每条CI Rule的incomplete policy决定，Hard block、Dataset/Gold hash变化或业务状态被修改必须非零。完整human-authored/Live Release suite在受控手动或定时环境运行，不拖垮每次PR。

## 22. 推荐目录与文件边界

### 22.1 新增

```text
backend/app/evaluation/
  __init__.py
  schemas.py
  stable_ids.py
  subjects.py
  dataset_catalog.py
  store_protocol.py
  in_memory_store.py
  artifact_resolver.py
  business_equivalence.py
  metric_engine.py
  comparator.py
  baseline_service.py
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
  verification_service.py
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

### v1.9.0-a：Schema、Subject、严格 Component 合同、Dataset 与 Mock Runner

- 输入：正式v1.8 Subject（Commit `db6685a45baa5f75e4856cbc406e410ad313f332`/Tag `v1.8.0`）、现有70个synthetic case、空Alignment catalog、现有Metric函数。
- 输出：EvaluationSubject、六类Input/Gold/Outcome、Dataset/Fixture合同、MetricDefinition、稳定ID/hash、`EvaluationStoreProtocol`与`InMemoryEvaluationStore`、legacy importer、Mock Runner、Alignment双标工具/validator。
- 修改文件：新增evaluation schemas/subject/dataset catalog/store protocol/in-memory store、catalog validator与tests；不实现SQLite，不执行业务Graph。
- 新增依赖：无。
- 测试：Subject clean/worktree规则、strict discriminated union、Schema size、Frozen immutability、Reference/Candidate fixture、Gold完整性、Locked leakage、旧40/30 case无损导入。
- 验收标准：正式Subject完整固定；当前资产准确标为synthetic；Alignment为空时not_evaluable/`ALIGNMENT_BENCHMARK_PENDING`；若Gold完成则6 pair/92 case双标、Evidence与hash全部校验。
- 回滚点：不注册Runner，删除新Catalog/Protocol；旧评测脚本继续可用。

### v1.9.0-b：六类 Adapter、业务等价合同与 Artifact Resolver

- 输入：Frozen Dataset/Metric合同、Store Protocol、v1.4～v1.8公开只读Service。
- 输出：六类Component Adapter、strict CaseResult、FaultProfile、BusinessEquivalenceContract、受控EvaluationArtifactResolver与Candidate Index隔离策略。
- 修改文件：新增adapters/equivalence/artifact resolver及component integration tests；业务Service不为指标改语义。
- 新增依赖：无。
- 测试：adapter/repo/version隔离、execution与quality分离、single-case failure、Mock/Fake、Resolver path/hash/access、Recorder on/off canonical compare、business Store无mutation。
- 验收标准：六类Adapter在offline或deterministic至少一种模式可运行；无Gold明确not_evaluable；Candidate Index不触碰reference/production；自动测试无网络。
- 回滚点：按component flag关闭Adapter；业务服务对Evaluation无反向依赖。

### v1.9.0-c：Metric、Fingerprint、Environment、Comparison、Baseline 与 Gate Profile

- 输入：CaseResult、MetricDefinition、Subject、Environment和兼容Baseline candidate。
- 输出：Metric Engine、Run Fingerprint、Comparison Scope、overall/subgroup报告、EvaluationBaselineBinding、RegressionGateConfig、CI/Release/Manual Profile。
- 修改文件：新增metric engine/comparator/baseline service/regression gate、报告脚本与tests。
- 新增依赖：无；统计优先标准库，新库需单独审批。
- 测试：手算/denominator、environment compatibility、common cases、atomic Baseline Binding、zero baseline relative delta、min sample/incomplete policy、warning/block、CI/Release差异。
- 验收标准：Run终态不可变；仅完整completed Run可Baseline；Overall不掩盖预冻结关键subgroup；不兼容Performance不Gate；阈值由真实Baseline冻结。
- 回滚点：保留Metric报告但关闭Comparison/Gate/Promotion写入口。

### v1.9.0-d：Bad Case Fingerprint、Occurrence、Verification 与 Promotion

- 输入：typed CaseResult/Metric、Trace/Evidence refs、Dataset Catalog与Gate Rule结果。
- 输出：suggestion-only Analyzer、fingerprint dedup、append-onlyOccurrence/Event、revision lock、人工Triage、Case-level Verification、Promotion与FixReference。
- 修改文件：新增bad_case analyzer/service、verification/promotion service、Store Protocol扩展和tests。
- 新增依赖：无。
- 测试：trigger分类、fingerprint/recurrence、stale revision、非法transition、promotion-before-fix、pre-fix reproduction、fixed requires typed Fix、unrelated Gate failure不阻止Case verification。
- 验收标准：自动建议不能确认root cause；相同失败不重复建Case；Promotion可在Fix前完成且旧Frozen不变；verified严格关联Regression Case与相关Hard Rule。
- 回滚点：停止新BadCase/Promotion写入；已生成append-only事件保持可读。

### v1.9.0-e：Replay、Artifact Readiness、Trial/Repeat 与受控 Live

- 输入：Artifact Resolver、Run/Checkpoint权限、source/replay Subject、Provider consent/budget、v1.8 Trace。
- 输出：Replay Analysis、Offline Replay、Live readiness、LiveTrialSpec、repeat汇总、新Run/Trace Link与隔离结果。
- 修改文件：新增replay/live experiment service、Trace taxonomy小版本扩展和tests；不改变Research/Alignment恢复规则。
- 新增依赖：无。
- 测试：offline无网络、artifact missing/hash mismatch、checkpoint unsafe、live consent/budget、independent trial IDs、mean/variance/failure rate、minimum repeats、original preserved、cancel/partial。
- 验收标准：默认只读/offline；Live显式授权且不写Gold/production active；单Trial不能Baseline；Trace/Artifact incomplete传播到Metric。
- 回滚点：`EVALUATION_LIVE_ENABLED=false`，保留analysis/offline。

### v1.9.0-f1：SQLite Store、Coordinator、Access Policy 与 API

- 输入：a～e冻结Schema和`EvaluationStoreProtocol`。
- 输出：独立Evaluation SQLite/migration、Baseline/Occurrence/Verification表、Lease Coordinator、Retry/Cancel、Access Policy、Evaluation/Bad Case API。
- 修改文件：新增evaluation store/migration/coordinator/access/api，仅受控修改main lifespan/router。
- 新增依赖：无。
- 测试：migration、Run/Subject immutability、Baseline atomic switch、lease/recovery/retry/cancel、case/provider cap、idempotency/pagination/access、Resolver reauthorization、Store failure。
- 验收标准：SQLite实现通过Protocol合同；partial不可Baseline；API默认关闭且live另行授权；业务Store/Trace/Checkpoint不被修改。
- 回滚点：关闭API/Coordinator，回退InMemory/offline；独立DB保留只读。

### v1.9.0-f2：Dashboard、CI、Baseline Promotion、性能与完整回归

- 输入：f1 Store/API、稳定Dataset/Comparison/Gate/Bad Case合同。
- 输出：Dashboard、显式Baseline Promotion、CI command、性能/故障报告、runbook与v1.9验收文档。
- 修改文件：新增frontend evaluation feature、CI/benchmark scripts和docs，仅受控修改router/AppShell。
- 新增依赖：优先无；前端新库需独立审查。
- 测试：Dashboard common/incompatible scope、Bad Case occurrence/verification、CI/Release profile、large result、Baseline权限、full backend/frontend/build/validate。
- 验收标准：CI确定性无网络/业务写入；Dashboard不早于合同且不把partial显示成完整；完整回归通过；`ALIGNMENT_BENCHMARK_PENDING`如实关闭或保留。
- 回滚点：隐藏Dashboard/关闭Promotion与CI Gate；Store/API可独立保留只读。

每个阶段不得修改业务系统来迎合指标；任何业务适配只允许调用既有公开合同并通过等价/无写入测试。

## 24. 测试计划

### 24.1 Baseline、Subject、Dataset 与 Gold

- `test_v1_8_tag_and_commit_are_recorded`
- `test_formal_baseline_subject_requires_clean_commit`
- `test_formal_baseline_requires_commit_subject`
- `test_worktree_subject_cannot_be_promoted_as_formal_baseline`
- `test_worktree_subject_cannot_be_formal_baseline`
- `test_subject_hash_changes_when_config_changes`
- `test_subject_hash_changes_when_prompt_profile_changes`
- `test_frozen_dataset_version_is_immutable`
- `test_case_or_gold_change_creates_new_dataset_version`
- `test_locked_test_never_enters_fit_or_threshold_selection`
- `test_gold_cannot_be_generated_by_system_under_test`
- `test_fixture_repo_index_paper_hashes_are_fixed`
- `test_component_gold_discriminator`
- `test_answer_gold_required_points`
- `test_observability_gold_forbidden_attributes`
- `test_annotator_identity_is_hashed`
- `test_alignment_empty_dataset_keeps_pending_gate`
- `test_alignment_double_annotation_and_adjudication_required`

### 24.2 Run、Baseline、Case Result 与 Index Fixture

- `test_evaluation_run_is_immutable_after_completion`
- `test_completed_run_is_immutable`
- `test_baseline_binding_is_separate_from_run`
- `test_partial_run_cannot_be_promoted_to_baseline`
- `test_partial_run_cannot_be_baseline`
- `test_baseline_binding_supersedes_previous_binding_atomically`
- `test_promoting_baseline_does_not_modify_source_run`
- `test_execution_error_is_not_quality_failure`
- `test_execution_error_and_quality_failure_are_distinct`
- `test_completed_case_can_fail_quality_gold`
- `test_missing_gold_returns_not_evaluable`
- `test_not_evaluable_component_is_not_failed`
- `test_incomplete_input_returns_indeterminate`
- `test_candidate_index_is_built_in_isolated_namespace`
- `test_reference_index_is_never_overwritten`
- `test_reference_and_candidate_index_are_separate`
- `test_index_fixture_change_requires_new_dataset_version`
- `test_retrieval_case_does_not_follow_production_active_index`

### 24.3 Adapter、Artifact、业务等价与 Metric

- `test_six_component_adapters_use_repo_version_isolation`
- `test_adapter_failure_isolated_to_one_case`
- `test_offline_adapter_does_not_execute_business_flow`
- `test_deterministic_adapter_uses_mock_and_fixed_checkpoint`
- `test_artifact_resolver_rejects_arbitrary_path`
- `test_artifact_hash_mismatch_marks_result_incomplete`
- `test_telemetry_ids_are_ignored_in_business_equivalence`
- `test_recorder_on_off_uses_canonical_comparator`
- `test_retrieval_ranking_difference_breaks_equivalence`
- `test_agent_terminal_status_difference_breaks_equivalence`
- `test_float_tolerance_is_versioned`
- `test_metric_hand_calculation_and_denominator_policy`
- `test_overall_and_subgroup_metrics_are_both_reported`
- `test_incomplete_trace_produces_incomplete_metric`
- `test_llm_judge_is_not_primary_metric`

### 24.4 Fingerprint、Comparison 与 Gate

- `test_run_fingerprint_compatibility`
- `test_comparison_requires_compatible_dataset_and_metric_versions`
- `test_performance_comparison_requires_same_environment`
- `test_partial_comparison_reports_common_cases`
- `test_absolute_and_relative_delta`
- `test_gate_config_is_versioned`
- `test_gate_rules_are_frozen_before_run`
- `test_critical_subgroups_are_frozen_before_result`
- `test_low_sample_count_uses_incomplete_policy`
- `test_relative_delta_handles_zero_baseline`
- `test_warning_rule_does_not_block_release`
- `test_block_rule_blocks_gate`
- `test_ci_and_release_profiles_differ`
- `test_subgroup_regression_blocks_quality_gate`
- `test_cross_repo_leak_blocks_hard_gate`
- `test_invalid_tool_call_blocks_hard_gate`
- `test_secret_leak_blocks_hard_gate`
- `test_incomplete_hard_input_is_indeterminate`
- `test_performance_gate_separates_cold_and_warm_runs`

### 24.5 Bad Case、Occurrence、Promotion 与 Verification

- `test_bad_case_events_are_append_only`
- `test_bad_case_conflicts_on_stale_revision`
- `test_same_failure_adds_bad_case_occurrence`
- `test_bad_case_occurrence_deduplication`
- `test_root_cause_suggestion_change_does_not_change_fingerprint`
- `test_closed_bad_case_recurrence_is_recorded`
- `test_different_symptom_creates_distinct_bad_case`
- `test_fixed_is_not_verified`
- `test_bad_case_can_be_promoted_before_fix_exists`
- `test_promotion_before_fix`
- `test_fixed_status_requires_fix_reference`
- `test_configuration_fix_does_not_require_git_commit`
- `test_regression_case_must_reproduce_failure_before_freezing`
- `test_bad_case_can_verify_when_unrelated_case_still_fails`
- `test_case_level_verification`
- `test_verification_requires_matching_regression_case`
- `test_verification_requires_relevant_hard_rules`
- `test_closed_requires_verification_run`
- `test_analyzer_suggestion_does_not_confirm_root_cause`
- `test_promotion_creates_new_dataset_version`
- `test_promotion_preserves_bad_case_trace_and_fix_reference`
- `test_promotion_never_overwrites_gold`

### 24.6 Replay、Live Trial、Coordinator 与 API

- `test_offline_replay_has_no_network`
- `test_live_replay_requires_consent_budget_and_permission`
- `test_live_replay_creates_new_run_and_trace`
- `test_replay_never_overwrites_original_run`
- `test_live_trials_have_independent_runs_and_traces`
- `test_single_live_trial_cannot_be_formal_baseline`
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
| 正式v1.8基线后代码继续漂移 | Evaluation错误复用旧被测身份 | 正式基线固定`db6685a...`；任何代码/配置/Prompt/模型变化创建新Subject，worktree只能开发实验 |
| Subject hash遗漏有效配置 | 不同系统输出被当成同一对象 | subject字段allowlist、canonical hash、依赖锁/Provider revision测试与人工审计 |
| Gold错误 | 错误Gate和错误修复方向 | 双标/adjudication、Evidence、版本化、disputed不进主Gate |
| Benchmark泄漏 | Locked失去意义 | split权限、访问审计、fit配置禁止Locked、变更升版本 |
| Dataset过拟合 | 只优化小fixture | source/repo subgroup、未来真实多仓库扩展、Locked一次性策略 |
| 仓库分布差异 | Overall掩盖局部失败 | macro by repo/pair/tag/type和关键subgroup Gate |
| Reference/Candidate Index混用 | 污染Gold或生产active version | FixtureBinding、隔离namespace、禁止写回Dataset/active、专项无mutation测试 |
| `ALIGNMENT_BENCHMARK_PENDING` | 无法评估Alignment质量 | v1.9-a优先补6 pair/92 case；未完成则not_evaluable |
| Alignment标注成本 | 延迟质量闭环 | 授权清单、分批双标、工具只辅助定位、不自动Gold |
| LLM Judge偏差 | 自洽但错误的高分 | optional独立报告，确定性/人工Gold为主 |
| Replay产生费用/外发 | 成本和隐私事故 | 默认offline、live flag/permission/consent/budget/concurrency |
| Live不稳定 | 回归结果不可复现 | 固定revision/seed/config，重复实验单独报告，不替换Locked |
| 单次Live Trial偶然性 | 错误晋升Baseline | Gate Config冻结最小repeat，独立Run/Trace，报告方差/成功率/Provider失败率 |
| Trace不完整 | 性能/失败结论不精确 | complete flag、integrity统计、Gate indeterminate |
| Bad Case误归因 | 修错组件 | suggestion-only、人工confirm、Evidence、revision/event |
| Bad Case重复爆炸 | 相同失败重复建单 | 稳定fingerprint+Occurrence；recurrence append-only并显式reopen |
| Case-level修复被无关Gate阻断 | 已修问题无法验证 | BadCaseVerification只检查对应Case、Regression Case与相关Hard Rule |
| Regression无限增长 | CI变慢、维护成本高 | 最小化、去重、分层suite、retired但保留历史 |
| SQLite并发 | writer busy/部分结果 | 独立DB、Lease、短事务、bounded workers、case staging |
| CI时间过长 | 开发反馈慢 | 小deterministic regression每PR，完整suite定时/手动 |
| Evaluation影响业务 | 活跃版本/Run被污染 | 临时DB/namespace、只读Adapter、no mutation tests |
| Artifact locator越权/漂移 | 离线重放读取错误或敏感内容 | Resolver受控scheme、逐次授权、hash/size校验、API隐藏内部路径 |
| Baseline状态污染Run | Run历史被Promotion覆盖 | Run终态不可变，Binding独立、原子supersede、显式权限 |
| 环境不兼容的性能比较 | 误报性能回归 | Run Fingerprint与Environment/Cache/Concurrency/Hardware兼容门禁 |
| 指标版本漂移 | 历史比较失真 | MetricDefinition/version/config hash与compatibility check |
| Frozen数据误删 | Baseline不可复现 | FK/reference guard、retention legal hold、显式管理员操作 |

待冻结决策：首批真实repo-paper授权、Alignment标注者/仲裁流程、Answer Gold rubric、真实多仓库Dataset规模、EvaluationSubject canonical hash字段注册表、Metric Definition初版、CI/Release Gate阈值与关键subgroup、Baseline promotion权限、Environment硬件分档、Evaluation retention、case/provider concurrency、Live最小repeat/pricing profile、Artifact locator scheme、local/admin认证来源和CI时限。

## 26. Definition of Done

v1.9.0 只有同时满足以下条件才完成：

1. 正式v1.8基线记录并核验Commit `db6685a45baa5f75e4856cbc406e410ad313f332`与annotated Tag `v1.8.0`；Tag仅作标签，完整SHA作身份。
2. v1.9使用不可变`EvaluationSubject`描述被评测对象；Commit、配置、Prompt、模型、Provider revision或依赖锁变化都会生成新Subject/hash。
3. 正式Baseline只接受干净`code_commit`或版本完整的`combined` Subject，`worktree_patch_hash`为空；开发worktree Subject不得晋升。
4. `EvaluationRun`与`EvaluationBaselineBinding`完全分离；Run终态不可修改，Binding显式授权并原子supersede旧Binding。
5. Run状态只使用completed/partial/failed/cancelled等执行语义，不以active/superseded表达Baseline状态；partial/failed/cancelled不可Baseline。
6. Case `execution_status`与`evaluation_outcome`完全分离；execution error、quality failure、not_evaluable和indeterminate有独立代码与测试。
7. Index/Retrieval/Agent/Alignment/Answer/Observability六类Input、Gold与Outcome均为严格判别联合，无占位或任意字典。
8. Dataset支持dev/locked_test/regression和human/confirmed/synthetic来源；Frozen Version不可原地修改，Gold/Fixture变化只创建新Version。
9. 系统输出、Trace、Legacy Alignment和LLM Judge不能自动写Gold；Locked Test不进入fit、Prompt、权重或阈值选择。
10. Reference Index与Candidate Index严格分离；Candidate在隔离namespace构建，不写回Frozen Dataset、不切换production active，Retrieval/Agent不隐式跟随active Index。
11. 六类Adapter至少在offline或deterministic模式可运行，严格repo/index/paper隔离、Artifact授权/hash验证、单Case失败隔离和业务无写入。
12. Recorder On/Off使用版本化BusinessEquivalenceContract；Telemetry动态字段被规范化，但Retrieval排序、Agent状态/工具/Evidence、Answer/Citation、Alignment决策和Business Store必须等价。
13. Index/Retrieval/Agent/Alignment/Answer/Observability指标都有版本、denominator、empty/incomplete策略、手算测试，并同时报告overall和subgroup。
14. `ALIGNMENT_BENCHMARK_PENDING`只有在真实双标/adjudicated Gold完成后关闭；未完成时继续显式保留，Alignment质量指标not_evaluable且不得宣称Quality完成。
15. Answer主指标基于人工/确定性Gold points与Citation事实；LLM Judge仅为optional辅助，不能成为主要Gate依据。
16. Observability报告Completeness/Integrity/Link/Redaction/Drop/Overhead；partial/unknown输入MetricResult为complete=false。
17. 每个Run保存Subject、Run Fingerprint与Execution Environment；Comparison保存共同/排除Case和兼容/不兼容Metric。
18. Quality只在严格共同Case Scope比较；Performance不比较不兼容硬件、OS、cache、并发、Provider region或Mode。
19. `RegressionGateConfig`版本化，Rule包含min sample、incomplete policy、severity、冻结关键subgroup及numerator/denominator/sample依据。
20. CI、Release与Manual Gate Profile分离；CI确定性小套件不因不可计算的非关键Calibration/P95永久阻断，Release Hard indeterminate必须block。
21. Hard Invariant能阻断跨repo/version、Invalid Tool、非法Citation、未知Alignment Candidate、Secret泄漏、Gold修改、Recorder业务不等价和未授权Live。
22. Bad Case以稳定fingerprint去重并append-only记录每次Occurrence；Analyzer版本/Root Cause建议变化不产生重复Bad Case，复发有明确recurrence/reopen事件。
23. Bad Case有revision锁和open→triaged→confirmed→fixing→fixed→verified→closed或rejected生命周期；自动Root Cause只建议，confirmed必须人工操作。
24. Promotion可在Fix前发生，但必须在冻结Regression Case前证明修复前稳定复现；旧Frozen Dataset永不修改。
25. 进入fixed必须有typed FixReference；configuration/prompt/model/dataset fix不得伪装Git Commit，dataset_fix不计为模型质量提升。
26. BadCaseVerification按对应Case、匹配Regression Case、相关Hard Rules和兼容性判断；无关Case/Gate失败不阻止已修Case验证。
27. Closed必须关联confirmed root cause、FixReference、Case-level Verification、verified Event和Evidence；fixed不等于verified。
28. EvaluationArtifactRef包含受控storage kind/locator/media/size/redaction/availability；Resolver逐次授权并校验hash，API不暴露内部绝对路径。
29. Offline Replay在Artifact readiness验证后无网络、无付费、无业务写入；缺失/过期/拒绝/hash mismatch产生not-ready或indeterminate。
30. Live Experiment支持trial group/repeat index/count/temperature/seed，Trial各有独立Evaluation/Business Run与Trace，并报告均值、方差、成功率和Provider Failure Rate。
31. 单次Live Trial不能晋升正式Baseline；Promotion满足Gate Config最小repeat、permission、consent、budget、版本与compatibility。
32. Replay创建新Subject/run_id/trace_id并保留原Run，不覆盖结果、不写Gold、不切换production active。
33. v1.9-a先提供Store Protocol/InMemory实现；SQLite只在f1实现，Dashboard不早于Dataset/Comparison/Gate合同。
34. Evaluation Store独立migration/Lease/retry/idempotency/short transaction/retention，并含Subjects、Environments、Baseline Bindings、BadCase Occurrences/Verifications；不修改业务Store/Trace/Checkpoint。
35. EvaluationRunCoordinator支持claim once、heartbeat、recovery、cancel、graceful shutdown、case/provider并发上限与progress，终态不可取消。
36. Evaluation Trace使用新Trace/Link/ArtifactRef，原Trace只读；Trace不完整传播到Metric但不能成为Gold。
37. API默认关闭，统一Access Policy、幂等、分页、大小、Subject/Baseline promotion权限、mode权限与稳定错误码均有合同测试。
38. Dashboard显示Subject、Run执行/质量、Comparison Scope、Gate Profile、BadCase Occurrence/Verification、Trace Link、Dataset Version和Promotion，不成为Gold算法源。
39. Trace Compare/Performance视图只在Fingerprint/Environment兼容时声明回归；部分或不兼容仅并排展示。
40. `v1.9.0-c`冻结Comparison/Baseline/Gate合同，`f1`完成Store/API，`f2`才完成Dashboard/CI/Baseline Promotion；各阶段独立回归。
41. CI deterministic suite显式选择Baseline Binding与CI Gate Config，无网络、模型下载、付费调用或业务写入，并按Rule policy返回退出码。
42. Evaluation On/Off时v1.4～v1.8业务结果、Retrieval排序、Run/Lease/Cancel、Checkpoint恢复、Alignment Decision/Deployment和Trace隐私语义保持不变。
43. 完整后端测试、前端测试/build和`scripts/validate.sh`通过，真实Baseline/Gate/故障注入结果写入v1.9验收文档。
44. v1.4事实ID、v1.5 Retrieval、v1.6 Agent、v1.7 Alignment、v1.8 Observability以及旧Analysis/报告/前端保持兼容。

本文件只定义 v1.9 后续实施方案；本轮未实现 Evaluation Runner、Regression Gate、Bad Case Store、Replay、Evaluation SQLite/API/Dashboard或任何正式 v1.9 功能代码。
