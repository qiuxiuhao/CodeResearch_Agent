# CodeResearch Agent v1.7.0：论文代码对齐 2.0 开发计划

状态：开工前审计、算法设计与实施边界冻结

正式事实基线：v1.6.0 Commit `c6c3337f12935cb5251a966e8ca673366f5e8cc2`，tag `v1.6.0`。

实施范围：v1.7.0-a 至 v1.7.0-f

## 0. 开工前置条件

v1.7.0-a 开始前必须全部满足：

1. v1.6.0 形成独立 Git commit，建议同时创建受保护的 `v1.6.0` tag；本计划届时必须把该完整 Commit SHA 写入“正式事实基线”。
2. 基线 commit 的工作树必须干净，不得把未提交修改或本地临时文件当作可复现事实。
3. 在该 commit 上重新执行并记录 `python -m pytest -q`、前端测试、前端 build 和 `scripts/validate.sh` 的真实结果。
4. `docs/baseline_v1.6.0.md` 必须引用同一完整 SHA、环境、数据库/Feature Flag 与 Agent Benchmark 事实。
5. v1.4～v1.6 兼容能力与已知限制完成冻结；若验收失败，先修复并重新生成 v1.6 commit，不得带病进入 v1.7。

当前门禁状态：**已满足**。v1.6.0 已形成独立 commit/tag；后端 312 passed、前端 29 passed、前端 build 与 `scripts/validate.sh` 均通过，基线记录已冻结。

## 1. 背景与目标

当前 Legacy 对齐把规则提取的每个论文 contribution 与文件、类、函数、模型模块和库调用做英文词项重叠打分。它能快速给出可解释基线，也已有 unmatched 和多目标输出，但候选来源单一、特征耦合在一个整数分数中，缺少概率校准、歧义表达、人工审核、版本化派生存储和可复现的论文—仓库级 Benchmark。

v1.7.0 将其升级为 evidence-first 的多阶段对齐系统：先形成带明确类型和粒度的 `PaperModuleProfile`，由多路召回产生高召回 Candidate，独立 Feature Extractor 输出可解释特征，Candidate-level Calibrator 估计候选匹配概率，Set Builder 再形成 Profile-level accepted/abstained/needs_review/no_implementation 决策；受约束 LLM 只验证 Top-K 已有候选，最后把原始输出与人工 Review 分层保存在独立派生库中。

成功标准不是强制每个论文模块命中一个代码实体，而是在 Locked Test 上同时报告候选召回、集合对齐、拒答、证据和校准质量，并能明确说出“没有实现”“多个候选均可能”或“需要人工审核”。

## 2. 当前代码事实

### 2.1 Legacy 对齐入口、Schema 与输出

| 文件/符号 | 实际事实 | v1.7 处理 |
| -- | -- | -- |
| `backend/app/agents/nodes/paper_analyze_node.py::paper_analyze_node` | 调用 PDF 规则解析 | 继续作为 Legacy 输入，不替换 |
| `backend/app/tools/paper_parse_tool.py::parse_paper_pdf` | 提取 title、section、最多 5 个 contribution、keyword、module name、page/evidence | 构建 Profile 的确定性来源之一 |
| `backend/app/schemas/paper.py` | `PaperAnalysis`、`PaperContribution`、`PaperCodeTarget`、`PaperCodeAlignmentItem` | 保持旧字段与语义 |
| `backend/app/agents/nodes/paper_code_align_node.py::paper_code_align_node` | 在规则论文分析后运行 `align_paper_to_code` | 保留 Legacy Baseline |
| `backend/app/tools/paper_code_align_tool.py::align_paper_to_code` | 生成 matched/unmatched 与最多 5 个目标 | 包装成 `legacy_alignment` Candidate source |
| `backend/app/agents/nodes/report_generate_node.py` | 写 `paper_code_alignment.json` 并生成旧报告 | 不修改 |

当前 `PaperAnalysis` 输入包括 contributions、keywords、module_names、section/page evidence；代码输入来自 repo index、file/class/function/function analysis、model analysis 和 library calls。Legacy 结果存入任务状态和 `paper_code_alignment.json`，不是独立对齐数据库。

### 2.2 Legacy 实际算法

`_build_code_targets()` 形成 file/class/function/model_module/library-call Candidate；`_normalize_terms()` 做英文正则 token、camel/snake 拆分、lowercase、短词过滤和简单复数去尾。

每个 contribution 的 query terms 来自 title、description、keywords，以及论文级全部 `module_names`。`_score_target()` 的实际分值为：

```text
论文文本精确包含非泛化代码名       +5，并标记 strong
非泛化关键词交集                  +交集数量
attention/encoder/head 等角色交集  +3，并标记 strong
双方包含 loss                     +2，并标记 strong
```

仅保留正分候选并按分数降序取前 5；只有 `top_score>=3` 且至少一个达到阈值的候选有 strong evidence 才 matched。输出目标是前 5 中所有 `score>=3 && strong` 的去重结果。置信度规则为 top score `>=7` 且证据项至少 2 为 high，`>=4` 为 medium，否则 low。

因此实际行为是：

- 支持一个 contribution 对多个代码目标（一对多）。
- 不同 contribution 可以复用同一 target（多对一）。
- 不是固定 Top-1。
- 支持 unmatched，可视为 Legacy 的弱拒答；但没有 `abstained`、ambiguous、`needs_review` 或经强负证据确认的 `no_implementation` 决策状态。
- 同分稳定性只依赖原始 Candidate 构造顺序；没有显式 margin、calibration 或 profile-aware 权重。
- 论文级全部 module_names 会进入每个 contribution，存在跨模块词项污染风险。

### 2.3 LLM/VLM 增强边界

`paper_code_align_llm_node()` 按 matched 优先、confidence 优先选择最多 `LLM_MAX_PAPER_ALIGNMENTS`（默认 5）条规则结果。Payload 只包含当前 contribution、规则 alignment、相关 Figure VLM 分析和现有 code evidence catalog。

`PaperCodeLinkValidator` 要求 possible link 使用当前 contribution、已允许 Figure 和已有 `paper_code_target` Evidence ID。Prompt 明确禁止改写规则 targets/status/confidence、禁止新增文件/类/函数/模块。因此当前 LLM 只能解释或建议已有候选，不能扩展候选召回，也不写回事实对齐。

### 2.4 `ALIGNS_WITH`、Retrieval 与 Agent 消费

`backend/app/indexing/index_service.py::_alignment_edges()` 在 structured index 构建时，把 Legacy matched target 映射到唯一 `CodeEntity`，并生成 contribution PaperEntity → CodeEntity 的 `ALIGNS_WITH` Edge；confidence 映射为 high 0.9、medium 0.65、low 0.35，`resolution_type="exact"`，metadata 保存 `legacy_reason`。

映射失败或同名不唯一时不产生 Edge。Edge Evidence 当前只指向论文 contribution/page，不包含代码行 Evidence。Edge 写入 v1.4 `knowledge_edges`，由 `RetrievalReadStore.graph_neighbors()` 按 repo/index version 查询。

v1.5 `paper_alignment` Profile 使用 Dense/Sparse/Graph 权重 1.2/0.8/1.5，允许 `ALIGNS_WITH|CONTAINS|DEFINES`、最多 2 hop。v1.6 `get_alignment` 只是此 Graph 查询的只读包装，不返回候选特征、校准状态、Review 或独立 alignment version。

### 2.5 现有测试覆盖

- `tests/test_paper_code_align_tool.py`：成功匹配、unmatched、仅泛化词拒绝、重复目标去重。
- `tests/test_paper_nodes.py`：PDF 规则解析与对齐节点集成。
- `tests/test_llm_workflow.py`、`tests/test_paper_code_link_validator.py`：结构化 Mock、Evidence catalog、未知 Figure/目标拒绝。
- `tests/test_langgraph_workflow.py`：Legacy JSON 落盘、alignment item/confidence 和图示。
- `tests/indexing/test_index_integration.py`：索引节点位于规则对齐之后、LLM/VLM 之前及旧输出兼容。
- Retrieval/Agent 测试覆盖 `ALIGNS_WITH` Graph 合同，但没有真实 6 对 repo-paper 的对齐质量 Benchmark。

### 2.6 必须保留的 Legacy Baseline

- `align_paper_to_code()` 的输入、输出和阈值行为保持不变，作为消融项 1。
- `paper_code_alignment.json`、旧报告、图示和旧 `ALIGNS_WITH` Edge 继续生成和读取。
- v1.7 结果是独立、版本化、可删除重建的派生决策，不覆盖或伪装成 Legacy 事实。
- v1.5 排序与 v1.6 Planner/Executor 主图不改变。

## 3. 本阶段目标

v1.7.0 仅实现：

1. Paper Module Profile。
2. exact/alias/Sparse/Dense/role/Graph/Figure/Legacy 多路 Candidate Generation。
3. 可解释多特征 Feature Extraction。
4. Profile-aware Alignment Scorer。
5. Pair-level Dev 校验的 Candidate Calibration、Profile Set Decision、Abstention 和 needs_review。
6. 只能验证 Top-K 的 Constrained LLM Verifier。
7. 独立 Alignment Store、版本状态机和 retention。
8. Append-only Human Review、effective revision 与 provenance。
9. 6 个 repo-paper pair 的 Dev/Locked Alignment Benchmark。
10. 新 Alignment API。
11. 显式 Deployment Profile 与 v1.6 `get_alignment` 的增量 Service 接入。

## 4. 非目标

本阶段明确排除：

- 重新解析代码 AST，或修改 CodeEntity/PaperEntity/Edge/Evidence/Chunk ID。
- 修改 v1.5 Dense/Sparse/Graph/RRF/Reranker 排序。
- 修改 v1.6 Router、Planner、Executor、Budget 或 Research Agent Graph 主逻辑。
- 自动修改用户仓库或生成补丁。
- Embedding、Scorer、Verifier 模型训练或微调。
- 让 LLM 在 Candidate 集合之外自由生成对齐目标。
- 完整 Trace 平台和 Bad Case 管理前端。
- PostgreSQL、Redis、Celery、Neo4j。
- 重写旧报告或强制修改现有前端。

## 5. 对齐语义

### 5.1 基本关系

一个 `PaperModuleProfile` 对应一个类型和粒度均明确的论文对齐单元，决策允许：

- 一对一：一个论文模块由一个代码实体实现。
- 一对多：模块由跨文件/多个方法/配置共同实现。
- 多对一：多个论文概念共享一个通用代码实体。
- 部分实现：仅覆盖论文模块的部分输入、分支、公式或训练阶段。
- 无实现：已有明确强负证据或人工确认仓库中没有实现；不能仅由低分或空候选推出。
- 歧义候选：多个代码实体证据接近，无法安全选择。
- abstain：证据或 calibration 不足，系统主动拒答。
- needs_review：候选有价值但达到人工审核带而非自动 accepted。

不得要求每个 Profile 至少有一个代码目标。`selections=[]` 是合法输出，但必须带 reason、召回源运行状态、feature/evidence coverage。多个 Selection 可以分别使用不同 relation type；多个 Profile 也可以选择同一个 CodeEntity。

### 5.2 决策状态

```text
accepted      有足够证据和校准置信度，可为一或多个 Candidate
abstained     系统没有足够证据安全决策
needs_review  位于歧义/阈值带，等待人工审核
no_implementation  有强负证据或人工 Review 确认没有实现
```

`rejected` 只描述某个 Candidate 的判断或人工 Review 动作，不是 Profile-level 状态。`partially_implements` 是单个 `AlignmentSelection` 的 relation type，不等同于低置信度。第一版自动系统以 `abstained` 为主要负向输出；`no_implementation` 主要由 Human Review 确认，只有满足第 12 节强负证据门槛时才允许自动产生。

## 6. Alignment Schema

新增 `backend/app/alignment/schemas.py`，Pydantic v2、`extra="forbid"`、所有可变字段使用 `default_factory`。持久对象均带 `schema_version`、所属 run/version，并在其职责范围内记录 source/provenance。

```python
AlignmentSource = Literal[
    "deterministic_rule", "legacy_alignment", "retrieval_sparse",
    "retrieval_dense", "code_graph", "figure_vlm", "structured_llm",
    "scorer", "calibrator", "llm_verifier", "human_review",
]

ProfileType = Literal[
    "module", "formula", "figure_module", "training_strategy",
    "inference_strategy", "configuration", "general_contribution",
]
ProfileGranularity = Literal[
    "paper", "section", "contribution", "figure_node", "formula",
]
AlignmentRelation = Literal[
    "implements", "partially_implements", "supports_training",
    "supports_inference", "configures",
]

class PaperModuleProfile(BaseModel):
    schema_version: str
    profile_id: str
    alignment_run_id: str
    repo_id: str
    index_version_id: str
    paper_id: str
    profile_type: ProfileType
    granularity: ProfileGranularity
    parent_profile_id: str | None
    source_group_key: str
    paper_entity_ids: list[str]
    canonical_name: str
    normalized_name: str
    aliases: list[str]
    abbreviations: list[str]
    role: str | None
    description: str
    inputs: list[str]
    outputs: list[str]
    formula_symbols: list[str]
    figure_neighbor_ids: list[str]
    contribution_ids: list[str]
    evidence_ids: list[str]
    extraction_sources: list[AlignmentSource]
    content_hash: str
    extractor_version: str
    profile_quality: float
    missing_fields: list[str]
    metadata: dict[str, JsonValue]

class CandidateSourceContribution(BaseModel):
    source: AlignmentSource
    source_rank: int | None
    source_score: float | None
    normalized_contribution: float | None
    evidence_ids: list[str]
    details: dict[str, JsonValue]

class AlignmentCandidate(BaseModel):
    schema_version: str
    candidate_id: str
    alignment_run_id: str
    profile_id: str
    code_entity_id: str
    candidate_status: Literal["recalled", "scored", "pruned"]
    source_contributions: list[CandidateSourceContribution]
    best_source_rank: int | None
    code_evidence_ids: list[str]
    retrieval_chunk_ids: list[str]
    generated_at: datetime

class AlignmentFeatureValue(BaseModel):
    feature_name: str
    value: float | None
    normalized_value: float | None
    available: bool
    missing_reason: str | None
    evidence_ids: list[str]
    explanation: str
    extractor_version: str

class AlignmentFeatureVector(BaseModel):
    schema_version: str
    vector_id: str
    alignment_run_id: str
    profile_id: str
    candidate_id: str
    features: list[AlignmentFeatureValue]
    available_weight_ratio: float
    required_weight_ratio: float
    coverage_penalty: float
    feature_schema_version: str
    content_hash: str

class AlignmentCandidateScore(BaseModel):
    schema_version: str
    score_id: str
    alignment_run_id: str
    profile_id: str
    candidate_id: str
    raw_available_feature_score: float
    available_weight_ratio: float
    required_weight_ratio: float
    coverage_penalty: float
    coverage_adjusted_score: float
    calibrated_match_probability: float | None
    calibration_profile_id: str | None
    feature_contributions: dict[str, float]
    reason_codes: list[str]

class AlignmentSelection(BaseModel):
    selection_id: str
    candidate_id: str
    relation_type: AlignmentRelation
    raw_score: float | None
    calibrated_match_probability: float | None
    paper_evidence_ids: list[str]
    code_evidence_ids: list[str]
    reason_codes: list[str]

class AlignmentDecisionConfidence(BaseModel):
    set_confidence: float | None
    auto_accept_probability: float | None
    has_implementation_probability: float | None

class AlignmentDecision(BaseModel):
    schema_version: str
    decision_id: str
    alignment_run_id: str
    profile_id: str
    decision_version: str
    status: Literal["accepted", "abstained", "needs_review", "no_implementation"]
    selections: list[AlignmentSelection]
    set_score: float | None
    set_coverage: float | None
    set_compatibility: float | None
    confidence: AlignmentDecisionConfidence
    top_margin: float | None
    decision_source: AlignmentSource
    scorer_profile_id: str
    verifier_id: str | None
    reason_codes: list[str]
    created_at: datetime

class AlignmentSelectionProposal(BaseModel):
    candidate_id: str
    relation_type: AlignmentRelation
    evidence_ids: list[str]
    reason_codes: list[str]

class AlignmentVerification(BaseModel):
    schema_version: str
    verification_id: str
    alignment_run_id: str
    profile_id: str
    allowed_candidate_ids: list[str]
    proposed_selections: list[AlignmentSelectionProposal]
    verdict: Literal["accept", "abstain", "needs_review"]
    evidence_ids: list[str]
    uncertainties: list[str]
    provider: str | None
    model: str | None
    model_revision: str | None
    prompt_version: str
    status: Literal["success", "fallback", "failed", "skipped"]
    token_usage: dict[str, int]

class AlignmentReviewSelection(BaseModel):
    candidate_id: str
    relation_type: AlignmentRelation
    paper_evidence_ids: list[str]
    code_evidence_ids: list[str]

class AlignmentReview(BaseModel):
    schema_version: str
    review_id: str
    decision_id: str
    action: Literal[
        "accept", "reject", "replace_candidate", "accept_multiple",
        "mark_no_implementation", "add_note",
    ]
    selections: list[AlignmentReviewSelection]
    note: str | None
    reviewer_scope_hash: str
    based_on_effective_revision: int
    review_sequence: int
    created_at: datetime

class EffectiveAlignmentDecision(BaseModel):
    decision_id: str
    decision_version: str
    effective_revision: int
    review_sequence: int
    status: Literal["accepted", "abstained", "needs_review", "no_implementation"]
    selections: list[AlignmentSelection]
    authority_level: Literal[
        "legacy_heuristic", "derived_scorer", "verified_model", "human_reviewed",
    ]
    applied_review_ids: list[str]

class AlignmentRun(BaseModel):
    schema_version: str
    run_id: str
    repo_id: str
    index_version_id: str
    paper_id: str
    input_hash: str
    model_profile_id: str
    attempt_number: int
    retry_of_run_id: str | None
    status: Literal[
        "queued", "profiling", "recalling", "featurizing", "scoring",
        "verifying", "ready", "active", "failed", "superseded", "cancelled",
    ]
    cancel_requested: bool
    current_stage: str | None
    profile_count: int
    candidate_count: int
    decision_count: int
    accepted_count: int
    abstained_count: int
    needs_review_count: int
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None

class AlignmentModelProfile(BaseModel):
    schema_version: str
    model_profile_id: str
    profile_extractor_version: str
    profile_llm_provider: str | None
    profile_llm_model: str | None
    profile_llm_revision: str | None
    profile_prompt_version: str | None
    figure_vlm_provider: str | None
    figure_vlm_model: str | None
    figure_vlm_revision: str | None
    figure_analysis_version: str
    candidate_generator_versions: dict[str, str]
    dense_retrieval_profile_hash: str | None
    sparse_retrieval_generation: str | None
    graph_policy_version: str
    legacy_alignment_version: str
    feature_schema_version: str
    scorer_version: str
    weight_config_version: str
    calibration_method: str
    calibration_version: str
    thresholds: dict[str, float]
    verifier_provider: str | None
    verifier_model: str | None
    verifier_revision: str | None
    verifier_prompt_version: str | None
    config_hash: str

class AlignmentDeployment(BaseModel):
    schema_version: str
    deployment_id: str
    deployment_name: str
    repo_id: str
    index_version_id: str
    paper_id: str
    model_profile_id: str
    active_run_id: str
    created_at: datetime
    updated_at: datetime
```

Candidate-level `calibrated_match_probability` 的监督标签严格是 `(profile_id, candidate_id) -> 0|1`；它不得表示整个 Selection 集合正确率、Profile 是否有实现或自动决策是否可靠。`AlignmentDecisionConfidence` 才承载 Profile-level 的 set/auto-accept/has-implementation 置信度。

ID 由 repo/index/paper/profile/entity 与 schema/version 的 canonical payload 生成；人工 Review 使用独立不可变 ID。Profile ID 的具体规则见第 7 节。模型、Prompt、VLM、Retrieval generation、Graph policy、权重、阈值或 Feature Schema 任一变化都必须改变 `config_hash/model_profile_id` 并形成新 Run，不能原地覆盖。

## 7. Paper Module Profile

### 7.1 输入和抽取来源

| 字段 | 确定性来源 | VLM 来源 | 可选结构化 LLM |
| -- | -- | -- | -- |
| canonical name / aliases | contribution title、module_names、section heading、括号缩写规则 | Figure module label | 仅在引用 Evidence 的情况下规范别名 |
| role / description | contribution/section 文本、角色词典 | Figure `modules.role`、flow | 结构化总结，不新增事实 |
| input/output | 章节句式、Figure flow、已有 PaperEntity | Figure inputs/outputs | 从给定证据抽取，必须返回 Evidence ID |
| formula symbols | 公式/文本 token 与邻近段落 | Figure 标签 | 只规范符号含义，不创造公式 |
| Figure neighbors | page、caption、contribution candidate | 已验证 FigureAnalysis | 不允许改变 Figure ID/page/bbox |
| contribution | Legacy `PaperContribution` | contribution candidates | 只能选择已有 contribution ID |

### 7.2 规则

- 固定生成流程：

```text
Paper contribution / section / figure / formula
→ 生成 profile candidate
→ 根据 source_group_key 合并等价来源
→ 固定 profile_type 和 granularity
→ 绑定 Evidence
→ 生成稳定 Profile ID
```

- Profile 首先由确定性规则产生；没有 LLM/VLM 也必须可运行，且每个 Profile 必须显式保存 `profile_type` 与 `granularity`。
- canonical name 采用 Unicode NFC、trim、空白压缩；normalized name 另做 lowercase、camel/snake/标点拆分，原文保留。
- abbreviation 只接受正文显式 `Long Name (ABC)`、`ABC (Long Name)` 或可证明的首字母形式。
- 相邻 Figure 以同 page、caption reference、section/contribution link 为依据，不能只按文件顺序猜测。
- 一个 contribution 可以拆成多个 Profile：当存在两个或以上具有独立名称/角色且能绑定不重叠 Evidence span 的模块时必须拆分；不能拆出的宏观贡献保留为 `general_contribution`。
- 同一 Section 中多个命名模块分别生成 Profile；Section 只提供共同 parent/source context，不把它们合并成一个大 Profile。
- 正文和 Figure 的同名节点仅在 normalized name/validated alias 一致，且 caption reference、section 或 contribution Evidence 至少一项可证明同一概念时合并；否则保持两个 Profile，并用 `parent_profile_id` 表达关系。
- Formula 在有独立公式 Entity、名称/编号且需要直接对齐代码变量或算子时生成 `profile_type=formula`、`granularity=formula` 的独立子 Profile；仅作为模块描述的零散符号继续作为所属模块 Feature，不强行拆分。
- 明确描述训练/推理策略且能绑定独立 Evidence 时分别生成 `training_strategy`/`inference_strategy`；仅作为某模块用途的句子保留为该模块 role/Feature。
- 明确超参数、配置方案或配置消融生成 `configuration` Profile；普通参数提及不单独成 Profile。
- 多个 PaperEntity 只有在同一 `source_group_key` 下才聚合。`source_group_key` 由 paper ID、profile type、规范化概念键、稳定 parent locator 和 extractor generation version 组成，不包含 Evidence 列表顺序。
- 结构化 LLM 输入只包含单个 Profile 的有界 Evidence catalog；输出必须引用已有 Evidence ID，通过 Pydantic 和业务 validator。
- LLM 输出是补充来源，不能覆盖规则字段；冲突放入 metadata/uncertainties。
- 没有 name、role 或 description 的 Profile 可以保留，但必须标记质量低并允许后续 abstain。

### 7.3 稳定 ID、合并与版本失效

```text
profile_id = SHA256(
  paper_id
  + profile_type
  + granularity
  + source_group_key
  + profile_generation_version
)
```

- Evidence ID、PaperEntity ID 和 aliases 在 canonical JSON 中排序去重，不因输入物理顺序改变 Profile ID。
- 拆分后各 Profile 使用不同 normalized concept key；合并只改变其 Evidence 集合和 content hash，不改变同 generation 的 ID。
- `profile_generation_version` 由 extractor version、拆分/合并 policy version 和 normalization version共同决定。
- Extractor 或 merge/split policy 变化必须改变 generation version，从而生成新的 Profile ID；旧 Profile 保留在旧 Run 中。
- Benchmark 固定 `profile_generation_version + profile_id`。若 generation 变化，必须升级 Benchmark dataset version并人工迁移/复核 Gold，不得静默重写 Locked Test ID。

## 8. Candidate Generator

### 8.1 多路召回

每个召回器只返回 `code_entity_id + rank/score + evidence`，由 `CandidateMerger` 去重：

1. exact/normalized name：CodeEntity name、qualified name、路径组件、camel/snake/dotted 规范化精确匹配。
2. alias/abbreviation：Profile 的经证据验证别名与缩写。
3. Sparse Retrieval：复用 v1.5 FTS/Qdrant Sparse 的只读 Service 和同 repo/version filter。
4. Dense Retrieval：复用 v1.5 Dense 接口；无模型时明确跳过，不阻断主链路。
5. role candidate：实体类型、model module role、training/inference/config/file role。
6. Code Graph：从初始高置信实体扩展 CONTAINS/DEFINES/CALLS/INSTANTIATES/IMPORTS 等 profile allowlist Edge，最多 2 hop。
7. Figure topology：Figure module/flow 与代码 model module/forward sequence 的局部拓扑候选。
8. Legacy alignment：将旧 matched targets/`ALIGNS_WITH` Edge 作为独立 source，不直接赋予最终 accepted。

### 8.2 合并、限额与解释

- Candidate 主键为当前 `index_version_id + code_entity_id`；多源命中合并所有 source/rank/contribution。
- 原始 Dense 与 BM25 分数不直接比较；召回融合使用 source-aware rank fusion 或配置化 normalized rank。
- exact/alias 不因 Dense 缺失而消失；Legacy 也不得压制其他召回源。
- 每 Profile 默认保留 Top 20、硬上限 50；每个 source 有独立 Top-K 和总时间预算。
- Candidate 只允许来自当前 repo/index version；不存在或 superseded snapshot 中的 ID 被拒绝。
- 召回阶段不调用 LLM 做自由搜索。
- 主要验收指标为 Candidate Recall@5/10/20 与 MRR；最终 Scorer 指标不能掩盖召回缺失。

## 9. Feature Extractor

每个 Feature 返回 `value|None`、normalized value、missing reason、Evidence ID、解释和 extractor version。Feature 状态区分 `available|missing|required_missing|not_applicable`：missing 不能当作 0，not-applicable 从该 Profile 的适用权重分母中排除，required_missing 则阻断自动 accepted。

| 特征 | 输入 | 计算方式 | 缺失与归一化 | 可解释输出 | 测试 |
| -- | -- | -- | -- | -- | -- |
| name | canonical/alias 与 entity name/qname/path | exact、token Jaccard、编辑相似、缩写命中组合 | 无名为 missing；裁剪到 0..1 | 命中的原串/alias/token | camel/snake、缩写、同名实体 |
| semantic | Profile description 与 SymbolChunk | 复用 Dense cosine 或离线 mock | 无模型/Chunk 为 missing；模型 profile 固定 | 模型 ID、chunk ID、raw/normalized score | Fake embedding、模型变化 |
| role | paper role 与 entity type/metadata | 版本化 role compatibility matrix | 角色未知为 missing | 命中的 role rule | encoder/head/loss/config |
| structure | Figure/Profile 层次与 Code Graph | 层次、邻居类型、局部 path 一致性 | 图缺失为 missing；hop decay 归一 | Edge ID/path | 一/二跳、环、噪声节点 |
| input/output | Profile IO 与 signature/docstring/flow | 规范 token/shape/semantic overlap | 单侧缺失为 missing | input/output 分项证据 | 参数名不同、部分匹配 |
| shape | tensor/维度描述与代码 shape evidence | 维数、符号、约束兼容度 | 未解析 shape 为 missing | shape pair 与冲突 | exact/compatible/conflict |
| formula/variable | 论文符号与代码变量/公式邻域 | 符号规范化、别名、同一 Evidence window | 无公式为 not-applicable，不扣分 | symbol→variable 映射 | 符号重名、缺失公式 |
| figure topology | Figure module/flow 与模型 module/forward | 有向局部图 node/edge overlap | 无 Figure 为 not-applicable | Figure/Code edge 对 | 缺图、反向边、重复模块 |
| evidence quality | paper/code evidence 完整度 | page/path/line、来源可靠度、交叉来源数量 | 无有效 Evidence 为 0 | 缺失项和 provenance | 非法 ID、缺行号、VLM-only |

Feature Extraction 不能重新解析 AST；只读取 v1.4 Entity/Edge/Evidence/Chunk、Legacy JSON 和已验证 Paper/Figure 数据。

为防止仅 Name 可用时经重归一得到虚高分，统一计算：

```text
available_weight_ratio = available_applicable_weight / total_applicable_weight
coverage_penalty = min(1.0, available_weight_ratio / required_weight_ratio)
raw_available_feature_score = Σ(w_i * f_i) / Σ(available w_i)
coverage_adjusted_score = raw_available_feature_score * coverage_penalty
```

`required_weight_ratio` 和关键 Feature allowlist 按 `profile_type` 版本化。自动 accepted 必须同时满足 score、available ratio、evidence quality、关键 Feature 和 margin；名称完全一致但 structure/role/evidence 等必要特征缺失时只能 needs_review/abstained。

## 10. Scorer

### 10.1 固定评分与集合决策流程

```text
Feature Extraction
→ Candidate Raw Available-feature Score
→ Coverage-adjusted Candidate Score
→ Candidate-level Calibration
→ Candidate Selection
→ Set Compatibility/Coverage
→ Profile-level Decision
→ Abstention/Review
```

- 权重按 `module|formula|figure_module|training_strategy|inference_strategy|configuration|general_contribution` 配置，与 `PaperModuleProfile.profile_type` 一一对应。
- `weight_config_version`、feature schema、缺失策略和最低 coverage 进入 Model Profile hash。
- 输出每个 Feature 的实际权重、coverage penalty 和贡献，Top-K 排序使用 coverage-adjusted score、source diversity、entity ID 稳定 tie-break。
- `AlignmentCandidateScore.calibrated_match_probability` 只表示该 Candidate 是否属于 Profile 的正确实体集合，不得被 Profile decision 重新标注或复用成 set confidence。
- 多目标集合由 Candidate 概率、单 Candidate 阈值、pair compatibility 和 incremental coverage gain确定，默认最多 5 个；每个 `AlignmentSelection` 独立保存 relation type、概率与证据。
- Set Builder 输出 `set_score/set_coverage/set_compatibility`；`AlignmentDecisionConfidence` 再分别估计 set confidence、auto-accept probability 和 has-implementation probability。
- `top_margin = top1 - top2`，小 margin 进入 needs_review/abstain 带。
- Candidate 未入选或被 Review 拒绝不回写 Candidate status；`alignment_candidates` 只保存 recalled/scored/pruned，选择与拒绝存在 Decision/Selection/Verification/Review。
- 阈值和权重只通过第 10.2 节 4 个 Dev pair 的 pair-level 验证调整；Locked Test 只在 Model Profile 冻结后运行。

### 10.2 Calibration

第一版不依赖大规模训练。优先采用单调分箱 + Laplace smoothing；若训练 fold 的正负样本和 bin coverage 达到预设最低值，可比较仅两个参数的 Logistic/Platt Calibration，并记录优化器、seed 和版本。任何方法都必须和未校准 baseline 比较，并有恒等 fallback。

Calibration 监督单元固定为 `(profile_id,candidate_id)->0|1`，输出 Candidate match probability，不改写 raw feature。模型 profile、数据集版本、Profile generation 或 Feature Schema 变化均使 calibration 失效并要求重新拟合。

采用 4-fold leave-one-pair-out：每 fold 用 3 个 Dev repo-paper pair 拟合，用剩余 1 个 pair 验证；四个 fold 的 out-of-fold prediction 必须覆盖全部 Dev case。它用于选择 calibration 方法、检查权重/阈值稳定性并生成 Dev OOF Brier/ECE，不能按 Candidate 随机切分。

最终流程：

```text
4 个 Dev pair 做 leave-one-pair-out 方案选择
→ 用全部 4 个 Dev pair 拟合最终参数
→ 冻结 AlignmentModelProfile、fold assignment、bins、权重和阈值
→ 只运行一次 2 个 Locked Test pair
```

报告必须保存固定 bin 边界、每 bin 样本数、未校准 baseline、各 fold 与 pair-level macro 指标，并使用 pair bootstrap 给出置信区间；样本不足无法稳定 bootstrap 时必须明确小样本不确定性，不得输出伪精确结论。

## 11. Constrained LLM Verifier

Verifier 只接收 Scorer Top-K（默认 5、硬上限 10）的：Candidate ID、有限代码片段、Candidate probability、Feature contribution、Paper/Code Evidence catalog 和允许的 relation type。

约束：

- 输出为 `list[AlignmentSelectionProposal] + verdict + uncertainties`；每个 Proposal 独立指定 Candidate 与 relation。
- Proposal 中的 Candidate ID 必须是输入 Candidate ID 子集，可多选；模型不生成 selection ID、raw score 或 calibrated probability，这些由服务端复制可信 CandidateScore 后生成正式 `AlignmentSelection`。
- 可以 `abstain` 或 `needs_review`。
- 不得生成新路径、类名、函数名、Entity ID、行号、页码或 Evidence ID。
- 所有 Evidence ID 必须在 task-scoped catalog 中，定位字段由服务端事实覆盖。
- Pydantic 后再做 Candidate/Evidence/identity/cardinality 业务校验。
- Prompt/Provider/model/revision、consent、预算、token、latency 和 fallback 全部记录。
- Provider 不可用、未授权、超时或校验失败时回退到 Scorer decision，并附 warning。
- Verifier 只写派生 Verification/Decision，不写 v1.4 事实数据库或 Legacy Edge。
- Verifier 不能把 Profile-level confidence 回写为 Candidate probability，也不能给未知 Candidate 分配 relation。

Verifier 不保证必然提高质量；是否默认开启由 Locked Test 的准确率、abstention、unsupported rate、延迟和成本共同决定。

## 12. Abstention 与 Calibration

### 12.1 决策区间

阈值由 Dev Set 冻结，示意规则如下，具体数值不得预先写死为效果结论：

```text
candidate calibrated_match_probability >= candidate_accept_threshold
AND margin >= accept_margin
AND set compatibility/coverage 合格
AND feature/evidence coverage 合格
  → accepted

review_low <= candidate probability < candidate_accept_threshold
OR margin < accept_margin
OR 多目标集合有冲突
  → needs_review

输入质量、Evidence 或 feature coverage 不足
  → abstained

低分或空候选
  → abstained（默认，不得直接推出 no_implementation）

强负证据门槛或 Human Review 满足
  → no_implementation
```

`候选为空 ≠ 仓库无实现`。漏召回、Profile 抽取错误、Graph 不完整、Dense 缺失、命名差异、动态调用和分散实现都可能造成低分。第一版自动系统主要输出 abstained；自动 `no_implementation` 至少同时要求：

1. Profile quality 达标且类型/粒度明确。
2. Model Profile 要求的召回源都成功运行；任何 Dense/Graph/索引缺失都会阻断自动 no-implementation。
3. Candidate pipeline health、版本和 count/hash 校验正常。
4. 没有达到最低可信度的 Candidate。
5. 存在可引用的强负证据，或 Profile 类型本身经确定性规则判定不对应代码实现。
6. 通过 Human Review；若第一版启用极严格自动规则，其规则版本和误报必须单独验收。

具体 Candidate 的低分/人工拒绝记录在 CandidateScore reason 或 Review action 中，不改变整个 Profile 的状态。

### 12.2 报告

- Selective Accuracy：仅 accepted 自动决策中的准确率。
- Coverage：自动 accepted/no_implementation 占全部 Profile 的比例；abstained/needs_review 不计自动覆盖。
- Abstention Precision/Recall：对应该拒答样本的识别质量。
- Brier Score：calibrated probability 与 gold label 的均方误差。
- ECE：固定、版本化 bin 定义下的 Expected Calibration Error。

必须同时报告 coverage 与 selective accuracy，禁止通过全部 abstain 制造高准确率。阈值只看 Dev；Locked Test 不能回流调参。

## 13. Alignment Store

### 13.1 存储边界

使用独立派生数据库：

```text
data/paper_code_alignment.sqlite3
```

不修改 `structured_index.sqlite3` 和旧 `knowledge_edges` Schema。建议表：

- `alignment_runs`
- `alignment_run_leases`
- `alignment_model_profiles`
- `alignment_deployments`
- `paper_module_profiles`
- `alignment_candidates`
- `alignment_candidate_sources`
- `alignment_feature_values`
- `alignment_candidate_scores`
- `alignment_decisions`
- `alignment_selections`
- `alignment_verifications`
- `alignment_reviews`

### 13.2 主键、约束与索引

- `alignment_runs.run_id` 主键；同 request identity 使用递增 `attempt_number`，并以 `retry_of_run_id` 保存失败/取消后的重试链。
- Profile、Candidate、Feature、Decision 以 `run_id + id` 复合隔离；外键级联只删除同一派生 Run。
- Candidate 唯一约束 `(run_id,profile_id,code_entity_id)`。
- Candidate status 只允许 recalled/scored/pruned；Selection、拒绝和 Review 不 UPDATE Candidate。
- 每个 active run 对 `(repo_id,index_version_id,paper_id,model_profile_id)` 最多一个，使用条件唯一索引。
- 成功结果复用使用部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_alignment_successful_request
ON alignment_runs(repo_id,index_version_id,paper_id,input_hash,model_profile_id)
WHERE status IN ('ready','active','superseded');
```

- failed/cancelled 不参与上述唯一约束，允许相同输入创建新 attempt；失败历史保留。使用相同 Idempotency-Key 仍返回原请求，显式 retry 必须提供 `retry_of_run_id` 并使用新 Key 或服务端 retry action。
- `alignment_run_leases.run_id` 唯一，保存 owner、token hash、acquired/heartbeat/expires；同一 Run 同时最多一个未过期 Lease。
- Deployment 唯一约束建议为 `(deployment_name,repo_id,index_version_id,paper_id)`；`active_run_id` 必须属于同 repo/index/paper 和 `model_profile_id`。
- Review 仅追加，引用 immutable decision；不 UPDATE 原 Decision/Verification。
- 为 status、profile、candidate、code entity、decision、review pending、created_at 建立索引。

### 13.3 状态机、事务与幂等

```text
queued → profiling → recalling → featurizing → scoring
       → verifying → ready → active → superseded
任一构建态 → failed|cancelled
superseded → active 仅允许显式原子回滚
```

- 长时间 Profile/Candidate/Feature/Verifier 计算在 SQLite 写事务外完成，但不能长期只放内存；每阶段完成后用短事务写入该 Run 的 staging rows 和 stage manifest。
- 固定分阶段写入：创建非 active Run → profiling 写 Profile → recalling 写 Candidate/source → featurizing 写 Feature → scoring/verifying 写 Score/Decision/Selection/Verification → 完整性校验 → 最终短事务切换 active。
- API 默认查询只读取 Deployment 指向的 active Run；building/failed/cancelled 的 stage rows 只在 `GET run` 调试视图中按 caller scope 可见，绝不进入默认 alignment 或 Agent 读取。
- 短事务创建 run/lease；验证完成后 `BEGIN IMMEDIATE` 校验 stage count/hash/引用、原子激活并 supersede 前一版本。
- 失败不影响旧 active；查询只读 active 或调用方显式固定的 ready/superseded Run。
- 同 input/model profile 若已有 ready/active/superseded 成功结果则复用；若只有 failed/cancelled，则创建 `attempt_number+1` 的新 Run。不同配置产生新 Run。
- 同 request identity 的并发构建先查成功结果，再通过 Lease 和短事务 claim 防重；loser 返回可重试 `alignment_busy` 或等待后复用成功 Run。
- Cancel 只设置 `cancel_requested=true`；每阶段入口和持久化前检查。ready/active/superseded 不允许取消。
- retention 先确保无 Benchmark/API/Review 引用，再显式删除派生 Run；Legacy JSON/Edge 永不由 retention 删除。
- migration 使用标准库 sqlite3、编号 SQL 和 `PRAGMA user_version`；实施时新增的是独立 Alignment DB migration，不改 v1.4 事实库 migration。

### 13.4 Model Profile 与 Deployment 选择

不同 Model Profile 可以各有 active Run，但默认读取不得混合它们。部署选择规则固定为：

```text
调用方显式指定 model_profile_id / deployment_name
→ 读取该 Profile 对应的 active run

调用方未指定
→ 读取 repo + index_version + paper 的显式 default deployment

不存在 default
→ alignment_profile_required
```

- `alignment_deployments` 保存 deployment name、repo/index/paper、model profile 和 active run；切换必须由显式、审计化操作原子完成。
- API 响应必须回显实际 `deployment_id/model_profile_id/alignment_run_id`。
- Benchmark 始终固定 `model_profile_id + run_id/config_hash`，禁止读取会变化的 default。
- v1.6 `get_alignment` 只读取一个固定 Deployment Profile，不能合并多个 active profile。若旧工具输入没有 paper/profile，服务从 PaperEntity 或唯一 Legacy 邻居确定 paper；无法唯一确定时返回 `alignment_profile_required`，不猜测。
- 稳定错误增加 `alignment_profile_required`、`alignment_deployment_not_found`。

### 13.5 AlignmentRunCoordinator、Lease 与恢复

新增 `backend/app/services/alignment_run_coordinator.py`。本地第一版使用 FastAPI lifespan + 受控 asyncio Task Manager + `AlignmentStore` + SQLite Lease，不使用无人管理的裸 `asyncio.create_task()`。

```text
POST 创建 queued Run
→ Coordinator 原子 claim Lease
→ profiling/recalling/featurizing/scoring/verifying
→ 每阶段短事务持久化并续租
→ 完整性校验
→ 最终短事务 active
```

Coordinator 负责领取 queued、续租、防重复执行、阶段恢复、cancel 检查、任务异常收集和 graceful shutdown。应用启动扫描 queued 和 Lease 已过期的非终态 Run，从最后一个完整 stage manifest 恢复；应用关闭停止领取新 Run，给当前阶段有限收尾时间，未完成 Run 保留当前阶段与可恢复 Lease 状态，不误记业务失败。

Cancel API 设置 flag 后，当前阶段在安全边界停止，未开始阶段不再运行并转 cancelled；ready/active/superseded 返回 `alignment_cancel_not_allowed`。超时/崩溃后的 late stage result 必须先验证 Lease token 和 cancel flag，失效结果不得提交。

### 13.6 Agent 读取视图

Store 提供只读 `AlignmentReadService`：按 repo/index/paper/profile 返回 Legacy、v1.7 accepted 和 needs_review 候选，统一附 source、run/model/alignment version、Evidence 和 Review provenance。人工最新有效 Review 形成“effective view”，但原模型 Decision 永久可查。

## 14. Human Review

支持：Accept、Reject、Replace Candidate、Accept Multiple、Mark No Implementation、Add Note。

规则：

- 原模型 `AlignmentDecision` 不可修改并带 `decision_version`；确定性 effective reducer 按 `review_sequence` 应用 Review，输出单调递增的 `effective_revision`。
- 每次 Review 是不可变事件，记录 reviewer scope hash、时间、`based_on_effective_revision`、单调 `review_sequence` 和逐 Candidate relation/evidence。
- Review 提交旧 effective revision 时返回 HTTP 409 `review_conflict`；同一 Decision 的 sequence 由短事务分配，禁止客户端自选。
- Replace Candidate 第一版只允许从当前 alignment Run 已有 Candidate 集合中重新选择，并可只修改某一个 Selection 的 relation；不得新增候选集合之外的 Entity/path。
- 若确需加入当前 Candidate 集合外实体，标记为 v1.7 之后的受控 Candidate 补录功能；v1.7 不允许人工直接写任意 Entity/path。
- Human Review 不覆盖 Scorer/Verifier 原始输出；effective decision 由确定性 reducer 计算。
- Mark No Implementation 必须带 note 或结构化 reason。
- Mark No Implementation 是 Profile-level effective status，`selections=[]`；Reject 只拒绝具体 Candidate/Selection，不等价于无实现。
- Review API 不写 v1.4 KnowledgeEdge；未来如需事实提升必须另有显式 promotion 流程，不在 v1.7 范围。

## 15. Alignment Benchmark

### 15.1 数据集冻结

首版固定 6 个 repo-paper pair：

- Dev：4 对。
- Locked Test：2 对。
- 目标规模：72 个正例 module profile + 20 个 unalignable/hard negative，共 92 个 case。

分布至少覆盖：一对一、一对多、多对一、名称一致、命名差异、跨文件实现、Figure、Formula、training/config、no implementation 和多个相似候选。Locked Test 两对均必须包含负例、命名差异和多目标，且至少一对包含 Figure/Formula。

Gold 必须由人工阅读论文和代码后标注，不能从 Legacy、当前 Scorer 或 LLM 自动生成。每个 Gold 至少双人标注并记录 adjudication；无法一致的样本标为 disputed，不计入主指标但进入分析。

Dev 的所有拟合、权重/阈值选择和 Calibration 必须按 repo-paper pair 做 4-fold leave-one-pair-out；禁止把同一 pair 的 Profile/Candidate 分散到训练和验证两侧。Locked Test 两对不进入任何 fit、threshold search、bin selection 或 Model Profile 选择。

### 15.2 Schema

```json
{
  "benchmark_schema_version": "1",
  "dataset_version": "alignment-v1",
  "case_id": "pair01-module-001",
  "repo_paper_pair_id": "pair01",
  "split": "dev",
  "repo_id": "repo_...",
  "index_version_id": "idx_...",
  "paper_id": "paper_...",
  "profile_id": "profile_...",
  "profile_generation_version": "profile-gen-v1",
  "profile_type": "module",
  "granularity": "contribution",
  "paper_evidence_ids": ["ev_..."],
  "gold_selections": [
    {"code_entity_id": "ent_...", "relation_type": "implements"},
    {"code_entity_id": "ent_...2", "relation_type": "configures"}
  ],
  "alignable": true,
  "no_implementation_confirmed": false,
  "acceptable_alternative_sets": [],
  "required_code_evidence_ids": ["ev_..."],
  "difficulty": "hard",
  "tags": ["one_to_many", "name_mismatch"]
}
```

Gold ID 必须固定到不可变 repo/index/paper fixture；任何 ID、Gold 或 Locked Test 内容变化必须升级 dataset/schema version并保留旧版。

Extractor generation 变化会生成新 Profile ID，必须升级 dataset version、重新执行 Profile merge/split 审核并人工迁移 Gold；不能仅按名称自动替换 Locked ID。负例需区分 `no_implementation_confirmed=true` 与“当前系统应 abstain”的未知样本。

## 16. 指标

### Candidate

- Recall@5/10/20：任一或全部 Gold 的召回分别报告；一对多另报 set coverage。
- MRR：首个正确代码实体排名倒数。
- Source recall/contribution：各召回源和组合的增益。
- Candidate probability：pair-level OOF Brier/ECE、AUROC/PR-AUC（样本足够时）和固定 bin 样本数。

### Final

- Top-1 Accuracy：仅单目标或定义了主目标的 case。
- Top-3 Recall。
- Micro/Macro F1：按 profile—entity pair。
- Exact Set Match：多目标集合完全一致。
- Relation-aware Selection F1：Candidate 和逐 Selection relation 同时正确。
- Profile set confidence/auto-accept/has-implementation 分别校准和报告，禁止与 Candidate probability 合并。

### Abstention

- Abstention Precision/Recall。
- Selective Accuracy 与 Coverage 曲线。
- no-implementation F1。
- needs-review precision/yield。

### Evidence

- Paper Evidence Precision。
- Code Evidence Precision。
- Citation Validity。
- Unsupported Alignment Rate：accepted 但没有足够有效 Evidence 的比例。

### Calibration

- Brier Score。
- ECE（固定 bins）。
- reliability table/diagram 数据。
- 4-fold out-of-fold Brier/ECE、未校准 baseline、pair bootstrap CI 或小样本不确定性说明。

所有指标分别报告 Dev 与 Locked Test、macro by pair、按 relation/tag 的子集；同时记录 latency、Provider token/cost、failure/fallback。主结论以 Locked Test 为准。

## 17. 消融实验

在相同数据版本、索引版本、候选限额、seed 和阈值冻结协议下依次比较：

1. Legacy Heuristic。
2. Dense Only。
3. Sparse + Dense。
4. `+ Role`。
5. `+ Code Graph`。
6. `+ IO/Shape/Formula/Figure`。
7. `+ Constrained LLM Verifier`。
8. `+ Calibration/Abstention`。

每组同时报告 Candidate Recall、Final F1/Exact Set、Selective Accuracy/Coverage、Evidence、Calibration、P50/P95 latency、token/cost 和 fallback。Legacy 的 matched/unmatched 要通过适配器映射到同一评测 Schema，但不改变原算法。

LLM Verifier 与 Calibration 需要分别消融，不能把两者收益合并归因。所有方案先用 4-fold leave-one-pair-out 生成 Dev OOF 指标，比较 fold/pair 稳定性后才用全部 Dev 拟合并冻结 Model Profile；Locked Test 最终只运行一次。报告必须保存 fold assignments、fixed bins、每 bin 数量和未校准 baseline；若反复查看 Locked Test，必须升级数据版本并声明泄漏。

## 18. API 设计

新路由始终注册；`ALIGNMENT_ENABLED=false` 时返回 HTTP 503 `alignment_disabled`，以保持 OpenAPI 稳定。只设计以下接口：

### `POST /repositories/{repo_id}/alignments/runs`

请求：paper ID、固定/可选 active index version、显式 model profile、是否启用 verifier、external consent，以及可选 `retry_of_run_id`。HTTP 层解析并固定 repo/index/paper/model profile；返回 202 queued run，由 AlignmentRunCoordinator 执行。

Idempotency：同 caller scope + `Idempotency-Key` + canonical request hash 返回原 Run；同 Key 不同请求返回 409 `idempotency_key_conflict`；只保存 Key hash。

failed/cancelled 的显式 retry 必须引用原 Run，生成新 `attempt_number` 并使用新的 Idempotency-Key；ready/active/superseded 的同输入直接复用成功结果。

### `GET /alignments/runs/{run_id}`

返回状态、版本、计数、失败、模型 profile、阶段 latency 和 effective decisions 摘要；按 caller scope/repository 授权。

### `POST /alignments/runs/{run_id}/cancel`

只设置 `cancel_requested=true`；Coordinator 在当前阶段安全边界转 cancelled。ready/active/superseded 返回 409 `alignment_cancel_not_allowed`，重复 cancel 幂等。

### `GET /repositories/{repo_id}/alignments`

分页查询，必须指定或解析 `index_version_id` 和 paper；支持 status/relation/profile/entity/source/review filter。调用方显式指定 model profile/deployment 时读取其 active Run；未指定时读取显式 default deployment；不存在时返回 `alignment_profile_required`。响应回显 deployment/model profile/run，绝不合并多个 active profile。

### `GET /alignments/{decision_id}`

返回 Profile、Candidate source、Feature contribution、calibration、verification、Evidence 和 Review history；不返回 Secret、完整 Prompt 或无限源码。

### `POST /alignments/{decision_id}/reviews`

严格 Review Schema、caller scope、`based_on_effective_revision`、Candidate membership 和逐 Selection relation；成功追加 Review 并生成新 effective revision，旧 revision 冲突返回 409。

### `GET /alignments/reviews/pending`

分页返回 needs_review；必须按 caller 可访问 repo 过滤，禁止全局泄露。

### `PUT /repositories/{repo_id}/alignments/deployments/{deployment_name}`

显式选择 repo/index/paper 的 `model_profile_id + active_run_id`，短事务校验 Run 身份和 active 状态后切换 Deployment。默认 Deployment 不由“最新创建时间”隐式推断；切换操作必须授权和审计。

稳定错误码包括：`alignment_disabled`、`alignment_run_not_found`、`alignment_decision_not_found`、`alignment_version_not_found`、`alignment_version_not_ready`、`paper_not_found`、`candidate_not_in_run`、`review_conflict`、`idempotency_key_conflict`、`verifier_unavailable`、`alignment_busy`、`alignment_cancel_not_allowed`、`alignment_profile_required`、`alignment_deployment_not_found`、`invalid_alignment_filter`。

## 19. v1.6 Agent 接入

不修改 Planner 或 Executor 主逻辑，保持工具名和 `GetAlignmentInput` 基本合同。将 `get_alignment` handler 内部改为调用新的聚合只读 Service：

```text
Legacy ALIGNS_WITH Edge
+ v1.7 active accepted/effective decisions
+ v1.7 needs_review candidates（明确非事实）
→ provenance-aware ToolResult
```

要求：

- 每项显示 `source=legacy|v1.7_scorer|v1.7_verifier|human_review`、alignment deployment/run/model/version。
- 每项增加：

```text
authority_level = legacy_heuristic | derived_scorer | verified_model | human_reviewed
evidence_role = alignment_hypothesis | alignment_decision | code_fact | paper_fact
```

- Legacy 是 heuristic；Scorer accepted 是 derived decision；Verifier 通过是 verified-model decision；Human Review 是最高对齐决策层，但仍不能替代 AST 代码事实或论文页码事实。
- accepted/effective decision 可作为对齐证据；needs_review 只能作为不确定候选，不能让 Evidence Checker误判为充分事实。
- Legacy 和 v1.7 指向同一 entity 时去重但保留全部 provenance。
- v1.7 Store 不可用/flag off 时无损回退 Legacy；返回 warning，不改变 Agent Graph。
- repo/index version 必须与 Run 固定版本一致；不得读取另一个 active version。
- `get_alignment` 只读取显式或 default Deployment 指向的一个 Model Profile；多个 active Profile 不得直接混合。Benchmark/Agent Run 应记录实际 Deployment/Profile/Run。
- 所有 alignment hypothesis/decision 必须同时附原始 Code/Paper Evidence；`needs_review` 的 `evidence_role` 固定为 `alignment_hypothesis`。
- Tool Result 仍受最大 20 条和 2,000 字符摘要限制；完整 Feature 通过 Alignment API 查询，不塞入 Agent State。

## 20. 推荐目录与文件边界

### 20.1 新增

```text
backend/app/alignment/
  __init__.py
  schemas.py
  stable_ids.py
  paper_module_extractor.py
  candidate_generator.py
  candidate_merger.py
  feature_extractor.py
  scorer.py
  calibrator.py
  set_builder.py
  verifier.py
  review_service.py
  deployment_service.py
  alignment_service.py
  api.py

backend/app/persistence/
  alignment_store.py
  alignment_migrations/001_alignment.sql

backend/app/services/
  alignment_run_coordinator.py

evaluation/alignment/
  benchmark_v1.jsonl
  fixture_catalog_v1.json
  README.md

tests/alignment/
scripts/evaluate_alignment.py
```

### 20.2 修改

| 文件/区域 | 作用 | 约束 |
| -- | -- | -- |
| `backend/app/main.py` | 注册 Alignment API，并在 lifespan 管理 Coordinator | 旧路由和既有 lifespan 服务行为不变 |
| `backend/app/agents/research/tools/default_tools.py` | `get_alignment` 调用聚合 Read Service | 不改 Planner/Executor/Graph |
| `backend/app/agents/research/tool_registry.py` | 必要时扩展 typed provenance summary | 保持输入与预算兼容 |
| `pyproject.toml` | 仅在实际需要时增加可选 alignment extra | 默认旧安装不强制新模型 |
| README/architecture/evaluation/API/database docs | 使用、版本、评测、retention | 只记录真实验收结果 |

### 20.3 禁止修改

- `backend/app/tools/paper_code_align_tool.py` 的 Legacy 算法和旧 Schema。
- v1.4 事实表、Entity/Edge/Evidence/Chunk ID 和 migration。
- v1.5 Retrieval 排序、Query Profile 和 vector point 语义。
- v1.6 Router、Planner、Executor、Research Graph 和 Run 状态机。
- 旧 `paper_code_alignment.json`、报告、图示和现有分析 API。
- 整个 `frontend/`，除非未来单独批准审核 UI 阶段。

## 21. 分阶段实施

### v1.7.0-a：Schema、Profile 粒度、Gold、指标和 Legacy Baseline

- 输入：已提交并验收的正式 v1.6 Commit、Legacy Schema/JSON/Edge、v1.4 entity/evidence fixture、6 对人工选定 repo-paper。
- 输出：开工门禁记录；Profile type/granularity/merge-split/ID；AlignmentSelection；Candidate/Set 概率分层；Decision/effective revision；完整 Model Profile provenance；Deployment 语义；pair-level split；92-case 数据结构、指标、Legacy adapter 和全 Mock evaluator。
- 修改文件：新增 `alignment/schemas.py`、`stable_ids.py`、`evaluation/alignment/`、`scripts/evaluate_alignment.py`、基础测试。
- 新增依赖：无。
- 测试：Schema round-trip、Profile 类型/粒度、Selection 独立 relation、Candidate/Set 概率分离、稳定 ID、Review revision、Gold 引用完整性、one/many/no-implementation、指标手算、pair split 与 Dev/Locked 隔离。
- 验收标准：正式 v1.6 SHA/tag 和完整验收已冻结；6 pair=4 Dev+2 Locked；目标 72 正例+20 hard negative 全部通过双人标注/校验；Legacy 可重复评测；自动测试无网络。
- 回滚点：删除新增 Schema/evaluation 文件，Legacy 对齐不受影响。

### v1.7.0-b：Paper Module Profile

- 输入：PaperEntity、PaperAnalysis、Figure/Caption/VLM、Evidence。
- 输出：稳定 Profile ID、source_group_key、正文/Figure/Formula 聚合、确定性拆分/合并、profile type/granularity/quality/missing、可选受约束 LLM补充和 extractor generation 失效策略。
- 修改文件：新增 `paper_module_extractor.py`、Profile fixture/tests；必要时新增 Prompt Registry 项但不改旧 prompt。
- 新增依赖：无；复用现有 Provider Runtime。
- 测试：normalized name、abbreviation、同 contribution 多模块拆分、正文/Figure 合并、Formula 独立/Feature、IO、Figure neighbor、Evidence 顺序、extractor version、缺字段、VLM/LLM unavailable、非法 Evidence。
- 验收标准：所有 Benchmark module 产生显式类型/粒度和稳定 Profile；字段均有 source/Evidence 或明确 missing；LLM 不能新增 ID/page/bbox；同 generation 幂等，generation 变化明确失效并要求 Gold 迁移。
- 回滚点：关闭 `ALIGNMENT_PROFILE_LLM_ENABLED`，继续使用规则 Profile；不影响 Legacy。

### v1.7.0-c：Candidate Generator

- 输入：Profile、v1.4 Entity/Graph、v1.5 Retrieval、Legacy result。
- 输出：8 路召回、CandidateMerger、source contribution、Top-K 和 recall report。
- 修改文件：新增 `candidate_generator.py`、`candidate_merger.py`、read adapter、专项测试。
- 新增依赖：无；Dense 复用可选 v1.5 retrieval extra。
- 测试：exact/normalized、abbreviation、Sparse/Dense fake、role、Graph、Figure topology、Legacy、多源去重、repo/version 隔离。
- 验收标准：Dev Candidate Recall@20 达到冻结目标（建议门槛 `>=0.95`，若未达到则不得进入最终质量宣称）；Locked 只报告不调参；无 Dense 时 Sparse/规则/Graph 主链路可用。
- 回滚点：按 source feature flag 关闭新增召回器；Legacy adapter 独立保留。

### v1.7.0-d：Feature、Candidate Calibration、Set Builder 和 Profile Decision

- 输入：Profile + Candidate + Evidence/Graph/Chunk。
- 输出：`Feature → Candidate raw/coverage-adjusted score → Candidate calibration → Selection → set compatibility/coverage → Profile decision → abstention/review`，以及 9 类版本化 Feature 和贡献解释。
- 修改文件：新增 `feature_extractor.py`、`scorer.py`、`calibrator.py`、`set_builder.py` 和测试/Dev config。
- 新增依赖：无；首版校准使用标准库实现。
- 测试：每类 Feature、missing/not-applicable、coverage penalty、关键 Feature、Candidate/Set 概率分离、逐 Selection relation、margin、多目标集合、abstain/no-implementation 门槛、4-fold OOF Brier/ECE、Locked 防泄漏。
- 验收标准：同输入排序稳定；每个分数可分解；Name-only 不得满置信或自动 accepted；低 Evidence/feature coverage 和模型缺失不能产生 no_implementation；fold assignments/OOF/阈值均版本化。
- 回滚点：关闭 calibration/abstention增强并回到版本化 raw scorer；Legacy 不变。

### v1.7.0-e：Constrained LLM Verifier

- 输入：Scorer Top-K、Feature contribution、有界 Paper/Code Evidence catalog。
- 输出：`list[AlignmentSelectionProposal] + verdict + uncertainties`、严格 Candidate/relation/Evidence 校验、可信 AlignmentSelection 转换、Scorer fallback、token/latency/cost 记录。
- 修改文件：新增 `verifier.py`、新 prompt/schema validator、Mock tests。
- 新增依赖：无；复用现有 Provider Runtime。
- 测试：多选且独立 relation、abstain、needs_review、未知 Candidate/relation/Evidence/路径/行号拒绝、Candidate probability 不被改写、Provider timeout/invalid schema/no consent、自动测试不访问网络。
- 验收标准：未知 Candidate 选择 100% 被拒绝；模型不可用不影响 Scorer；所有成功 Verification 证据有效；Verifier 是否默认开启由 Locked 收益/代价决定。
- 回滚点：`ALIGNMENT_VERIFIER_ENABLED=false`，仅使用 Scorer/Calibration。

### v1.7.0-f：Store、Coordinator、API、Review、Deployment、Agent 接入和实验

- 输入：已验证 Profile/Candidate/Feature/Decision/Verification 与 v1.6 Tool Registry。
- 输出：独立 SQLite Store/migration、分阶段 staging、失败重试、AlignmentRunCoordinator/Lease/Cancel、Deployment Profile、effective reducer/Review revision、authority-aware `get_alignment`、8 组消融和验收文档。
- 修改文件：新增 `alignment_store.py`/migration、`alignment_run_coordinator.py`、deployment/review/API/service；仅按 20.2 修改 main/get_alignment/docs。
- 新增依赖：无。
- 测试：migration、stage visibility、failed/cancelled retry、Lease/Coordinator/recovery/shutdown/Cancel、事务/失败隔离、幂等/并发激活、Deployment 切换、retention、Review revision/conflict、API/flag/error、authority-aware Legacy merge、Agent回归。
- 验收标准：HTTP 202 均由受控 Coordinator 执行；同 Run 单 Lease；失败/取消可新 attempt；building rows 不进入默认查询；默认 Profile 显式且不混合；Legacy 不被覆盖；Review append-only；Dev/Locked 分开报告全部指标和消融；完整验收通过。
- 回滚点：关闭 `ALIGNMENT_ENABLED` 和 `ALIGNMENT_AGENT_INTEGRATION_ENABLED`；删除可重建派生 DB 前须确认；Legacy JSON/Edge/Agent fallback 继续工作。

## 22. 测试计划

| 场景 | 建议测试文件/Fixture | 关键断言 |
| -- | -- | -- |
| normalized name | `test_paper_module_profile.py` | NFC/camel/snake/标点稳定 |
| abbreviation | 同上 | 仅证据支持的缩写被接受 |
| 一对多 | `test_scorer.py` / multi_file_module | 集合 ID 与 coverage 正确 |
| 多对一 | 同上 / shared_backbone | Profile 独立、同 entity 可复用 |
| no implementation | `test_abstention.py` | 低分/缺模型只 abstain；强负证据或人工确认才 no_implementation |
| ambiguous candidate | 同上 / twin_encoders | 小 margin → needs_review |
| Candidate Recall | `test_candidate_generator.py` | Recall@5/10/20、MRR 手算正确 |
| Graph neighbor consistency | 同上 / cyclic_graph | 同版本、一/二 hop、环终止 |
| formula/variable missing | `test_feature_extractor.py` | not-applicable 与 0 分区分 |
| Figure topology missing | 同上 | 不扣作错误、不伪造拓扑 |
| LLM 未知 Candidate | `test_verifier.py` | Schema 后业务校验拒绝 |
| abstention | `test_abstention.py` | coverage/precision/recall 正确 |
| calibration | `test_calibrator.py` | Dev-only、Brier/ECE、版本变化失效 |
| repo/version 隔离 | `test_alignment_service.py` | 不能跨 repo/index/paper 召回/读取 |
| Human Review provenance | `test_review_service.py` | append-only、optimistic conflict |
| Legacy 不覆盖 | `test_alignment_store.py` | v1.4 Edge/旧 JSON 无写入 |
| `get_alignment` 合并 | `test_agent_alignment_tool.py` | Legacy/accepted/review provenance 去重 |
| Store 幂等 | `test_alignment_store.py` | 同 input/model 复用，计数稳定 |
| 激活失败 | 同上 | 旧 active 可查，新 run failed |
| LLM/网络离线 | `test_alignment_fallback.py` | 自动测试无真实网络/模型，Scorer 可用 |

### 22.1 必须具名的回归用例

Profile 粒度与 ID：

- `test_profile_type_is_explicit`
- `test_same_module_from_text_and_figure_is_merged_deterministically`
- `test_different_modules_in_same_contribution_are_split`
- `test_profile_id_stable_under_evidence_order_change`
- `test_profile_extractor_version_invalidates_profile_generation`

Selection 与概率分层：

- `test_one_to_many_candidates_have_independent_relations`
- `test_multiple_profiles_can_select_same_code_entity`
- `test_verifier_cannot_assign_relation_to_unknown_candidate`
- `test_review_can_change_relation_for_single_selection`
- `test_candidate_probability_and_set_confidence_are_distinct`
- `test_multi_candidate_set_decision_uses_candidate_probabilities`
- `test_profile_decision_does_not_relabel_candidate_probability`

Pair-level Calibration：

- `test_calibration_split_is_by_repo_paper_pair`
- `test_locked_pair_never_enters_calibration_fit`
- `test_out_of_fold_predictions_cover_all_dev_cases`
- `test_calibration_config_records_fold_assignments`

Abstention 与缺失特征：

- `test_low_scores_produce_abstain_not_no_implementation`
- `test_no_implementation_requires_strong_negative_or_human_review`
- `test_missing_dense_model_cannot_produce_no_implementation`
- `test_name_only_candidate_cannot_receive_full_confidence`
- `test_not_applicable_feature_does_not_reduce_coverage`
- `test_missing_required_feature_blocks_auto_accept`

Run、Coordinator 与可见性：

- `test_failed_run_can_retry_same_input`
- `test_cancelled_run_can_retry_same_input`
- `test_successful_ready_run_is_reused`
- `test_partial_stage_rows_not_visible_as_active`
- `test_alignment_coordinator_claims_run_once`
- `test_expired_alignment_lease_is_recovered`
- `test_cancel_stops_future_alignment_stages`
- `test_two_coordinators_cannot_execute_same_alignment_run`
- `test_graceful_shutdown_keeps_run_recoverable`

Deployment、Review 与 Agent：

- `test_default_alignment_profile_is_explicit`
- `test_multiple_active_profiles_are_not_implicitly_merged`
- `test_agent_alignment_uses_fixed_deployment_profile`
- `test_review_conflicts_on_stale_effective_revision`
- `test_review_sequence_is_monotonic`
- `test_agent_alignment_authority_and_evidence_role`
- `test_needs_review_is_hypothesis_not_sufficient_fact`

此外必须完整运行现有 Legacy、indexing、retrieval、agent、API、前端测试，证明 v1.4-v1.6 无回退。

## 23. 风险与缓解

| 风险 | 影响 | 缓解/待决策 |
| -- | -- | -- |
| v1.6 尚无正式提交基线 | v1.7 无法复现或混入未提交行为 | v1.7-a 阻断门禁：先独立 commit/tag、全验收和基线文档冻结 |
| Paper Module 抽取不稳定 | Profile 粒度、拆分合并与名称漂移 | 显式 type/granularity/source_group、规则优先、generation version、人工 Gold 迁移 |
| 论文与代码命名差异 | exact recall 低 | alias/abbrev + Sparse/Dense/role/Graph，多路召回先保 Recall |
| 多粒度 Entity | file/class/method 同时高分 | relation/profile-aware 粒度规则、集合兼容与 Review |
| 一对多 Gold | Top-1 指标误导 | Exact Set、pair F1、set coverage；多目标 compatibility |
| Figure/VLM 噪声 | 错误拓扑扩散 | VLM 仅一项特征、Evidence/uncertainty、missing fallback |
| Formula 符号歧义 | 单字母大量误匹配 | 局部 Evidence window、角色/shape 约束、低权重和 abstain |
| Code Graph 不完整 | 召回/结构分低 | unresolved 保留、Graph 缺失不当 0、其他召回源独立 |
| Score/Calibration 过拟合 | 仅 4 个 Dev pair，单仓库主导 | leave-one-pair-out OOF、fold stability、pair macro/bootstrap、Locked 冻结 |
| Verifier 偏置 | 偏好名称相似或 Legacy | Candidate 随机化消融、受控 top-K、和 Scorer 分开报告 |
| Benchmark 泄漏 | Locked 失去意义 | 固定 ID/hash、访问记录、变更升版本、未来 repo holdout |
| 人工标注成本 | 92 case 双标耗时 | 分阶段标注、工具只辅助定位、不自动生成 Gold |
| Calibration 样本不足 | Candidate/Set 概率不可靠 | Candidate 标签单义化、单调分箱/恒等 fallback、fixed bins、CI/小样本声明 |
| Missing Feature 虚高 | 仅 Name 可用却重归一接近 1 | coverage penalty、required ratio/Feature、Evidence gate、自动 abstain |
| Dense/Provider 不可用 | 候选或 verifier 退化 | Sparse/规则/Graph/Scorer 可独立工作，明确 fallback |
| 派生库与事实库版本错位 | 返回旧 Entity | 全链路固定 repo/index/paper，激活前引用完整性校验 |
| Run 重试与并发重复 | 失败无法重试或同 Run 双执行 | attempt/retry chain、成功部分唯一、SQLite Lease、Coordinator token 校验 |
| 多个 active Model Profile | API/Agent 混合不可比决策 | 显式 Deployment/default，响应回显 Profile/Run，不隐式合并 |
| Review 并发覆盖 | 人工结论丢失或乱序 | immutable event、effective revision、monotonic sequence、409 冲突 |
| Coordinator 关闭/崩溃 | stage 半完成或误记失败 | stage manifest、短事务、lease expiry recovery、graceful shutdown |
| Legacy 兼容 | 新结果改变旧报告/Agent | 独立 DB、聚合只读 Service、feature flag、Legacy 优先 fallback |

开工前待冻结决策：正式 v1.6 Commit SHA/tag、6 对具体 repo-paper 清单与授权、Gold 双标流程、Profile merge/split generation、Feature 初始权重与 required ratio、Dev fold/阈值搜索范围、Calibration 最低样本数与 bins、Verifier 默认关闭/开启条件、Default Deployment 命名、Review caller 身份边界和 Alignment DB retention/lease 周期。

## 24. Definition of Done

v1.7.0 只有同时满足以下条件才完成：

1. v1.7 基于明确提交、完整验收并建议带 `v1.6.0` tag 的 v1.6 Commit；计划和验收文档记录同一完整 SHA，未提交工作树不得作为基线。
2. 所有核心 Schema 均有严格校验、JSON round-trip、版本/source/provenance 和稳定 ID 测试。
3. 每个 PaperModuleProfile 都有显式 profile type、granularity、source_group_key 和 generation version。
4. contribution/section/text/Figure/Formula 的 merge/split 规则固定；Evidence 顺序不影响 ID，Extractor policy 变化明确生成新 ID 并升级 Benchmark。
5. 一对多由多个 AlignmentSelection 表达，每个 Candidate 可独立保存 relation、Candidate probability 和 Evidence；多个 Profile 可选择同一 CodeEntity。
6. Candidate match probability、Profile set confidence、auto-accept probability 和 has-implementation probability 在 Schema、训练标签、Store、API 与指标中完全分离。
7. Calibration 使用按 repo-paper pair 的 4-fold leave-one-pair-out；OOF 覆盖全部 Dev case，fold assignments/fixed bins/未校准 baseline 被记录，Locked 不参与拟合或阈值选择。
8. 低分、空候选、Dense/Graph/模型不可用或 Feature 缺失不能自动产生 no_implementation；第一版默认 abstain，no_implementation 需要强负证据或 Human Review。
9. Candidate Generator 保留全部 source/rank/contribution，跨源按 entity 去重且严格 repo/index 隔离；Dev Candidate Recall@20 建议门槛 `>=0.95`，Locked 结果如实报告。
10. name/semantic/role/structure/IO/shape/formula/Figure/evidence quality 均解释 available/missing/not-applicable、归一化、Evidence 和版本。
11. Missing Feature 使用 available/required weight ratio 和 coverage penalty；Name-only 不会获得满置信度，关键 Feature 缺失阻断自动 accepted。
12. Scorer/Set Builder 同输入完全稳定，逐 Feature/coverage/set contribution 可复算；Candidate table 只保存 recalled/scored/pruned，不保存 selected/rejected Decision 状态。
13. LLM Verifier 只输出已有 Candidate 的逐项 relation Proposal，可多选/abstain/review；任何未知 Candidate/Evidence/定位字段或 relation 100% 被拒绝，且不能改写 Candidate probability。
14. Provider/模型/网络不可用时无损回退 Scorer；自动测试不下载模型、不访问网络、不产生付费调用。
15. failed/cancelled Run 可用相同输入创建递增 attempt 并保留 retry chain；ready/active/superseded 成功结果可幂等复用。
16. Profile/Candidate/Feature/Score/Decision 分阶段短事务持久化，长计算不持有写事务；building/failed/cancelled rows 在 active 前不进入默认查询。
17. HTTP 202 Run 由受控 AlignmentRunCoordinator 执行；queued/过期 Lease 可恢复，graceful shutdown 不误记失败。
18. 同一 Alignment Run 同时最多一个有效 Lease，失效/迟到 stage result 不能提交。
19. Cancel API、cancel_requested 和 cancelled 状态闭合；取消阻止未来阶段，ready/active/superseded 不允许取消。
20. 多个 active Model Profile 不会被默认混合；调用方显式 Profile/Deployment 优先，未指定必须存在显式 default，否则返回 `alignment_profile_required`。
21. Benchmark 和 v1.6 `get_alignment` 固定实际 deployment/model profile/run；API 回显三者，Deployment 切换为显式原子操作。
22. Human Review append-only；原 Decision 不可修改，effective revision 与 review sequence 单调，旧 revision 并发提交返回 HTTP 409。
23. Replace Candidate 第一版只能选择当前 Run 已有 Candidate；Review 可单独改变某个 Selection relation，不允许写任意 Entity/path。
24. AlignmentModelProfile 完整记录 Profile LLM、Figure VLM、Dense/Sparse、Graph、Legacy、Feature、Scorer、Calibration、阈值和 Verifier provenance；任一有效配置变化都改变 config hash/model profile ID。
25. 独立 `paper_code_alignment.sqlite3` 具编号 migration、Lease、状态机、部分唯一成功索引、失败隔离、历史版本和显式 retention；不修改 v1.4 事实库。
26. Agent Tool 区分 legacy_heuristic、derived_scorer、verified_model、human_reviewed authority，以及 hypothesis/decision/code fact/paper fact evidence role；needs_review 不会被当作确定性事实。
27. 6 个 repo-paper pair 固定为 4 Dev + 2 Locked，目标 72 正例与 20 hard negative；Gold 为人工双标、relation-aware、profile-generation-aware 并版本化。
28. Final 指标报告 Candidate Recall/MRR/OOF calibration、Top-1/3、relation-aware Micro/Macro F1、Exact Set、Selective Accuracy/Coverage、Evidence、Brier/ECE、pair macro/CI。
29. Legacy Heuristic 可在同一 Benchmark Schema 上复现；8 组消融分别报告 Dev OOF/Locked 的质量、覆盖、校准、延迟、token/cost、failure/fallback。
30. Alignment API 路由稳定；flag off 返回 503；Idempotency、retry、cancel、分页、错误结构、caller/repo/version/profile 隔离均有合同测试。
31. 完整 `python -m pytest -q`、前端测试、前端 build 和 `scripts/validate.sh` 通过，真实结果写入 v1.7 验收文档。
32. v1.4 Entity/Edge/Evidence/Chunk、v1.5 Retrieval 排序、v1.6 Agent 状态/API、旧分析 JSON/报告/Edge 和前端保持 Schema 与规范化语义兼容。

本文件只定义后续实施方案；本轮审计不实现 Paper Module Extractor、Candidate Generator、Feature Scorer、Verifier、Store、API、Review 或 Agent 接入代码。
