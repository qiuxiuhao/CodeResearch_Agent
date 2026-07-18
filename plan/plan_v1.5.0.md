# CodeResearch Agent v1.5.0：代码结构感知 Hybrid RAG 开发计划

状态：开工前技术调查与设计冻结  
基线：v1.4.0 / `04ea17e`  
实施范围：v1.5.0-a 至 v1.5.0-f

## 1. 背景与目标

v1.4.0 已将仓库扫描、Python AST、模型规则和论文规则事实统一为稳定的 Entity、Edge、Evidence、SymbolChunk 和版本化 SQLite 快照。下一阶段不再把整个仓库或松散 JSON 直接交给模型，而是把 active index 中的事实转换为可过滤、可解释、可复现和可评测的 Hybrid RAG。

v1.5.0 使用固定单轮管线，顺序冻结为：

```text
Query Profile
→ Dense Retrieval + Sparse Retrieval
→ Preliminary RRF（仅选择 Graph seed）
→ Graph Seed Selection
→ Graph Expansion
→ Final Weighted RRF（Dense + Sparse + Graph）
→ Optional Reranker Hybrid Fusion
→ Context Builder
→ Answer Generator
→ Citation Validator
→ Research Response
```

Dense 相似度、BM25/FTS 分数和 Graph 分数的数值空间不同，禁止直接比较或相加；它们只能通过各自稳定 rank 进入两阶段 RRF。任何候选和回答都必须追溯到 `repo_id + index_version_id + entity/chunk/evidence ID`。

本阶段的核心成功标准不是“能回答任意问题”，而是建立一套有 30～50 条固定 gold 数据、可运行消融实验、离线可回归的检索系统。

## 2. 当前代码事实

### 2.1 可复用实现

| 文件/组件 | 实际能力 | v1.5 用法 |
| -- | -- | -- |
| `backend/app/domain/entities.py` | `CodeEntity`、`PaperEntity` 及稳定事实字段 | 过滤、展示、父子去重、证据标题 |
| `backend/app/domain/edges.py` | `KnowledgeEdge`，保留 unresolved/ambiguous | Graph Expansion 和关系说明 |
| `backend/app/domain/evidence.py` | 代码行号、论文页码/Figure/bbox | `RetrievalEvidence` 与回答引用 |
| `backend/app/domain/index_manifest.py` | `SymbolChunk`、`IndexedFile`、`IndexManifest` | 检索文档、增量同步和版本校验 |
| `backend/app/indexing/stable_ids.py` | repo/entity/edge/chunk/content hash | Qdrant point 映射、gold ID、去重 |
| `backend/app/indexing/index_service.py` | active 快照构建、Manifest、失败隔离 | 检索同步的事实输入，不在此处嵌入模型 |
| `backend/app/persistence/index_store.py` | 版本状态机、短事务、retry/lease | 扩展只读 snapshot/graph 查询接口 |
| `backend/app/persistence/migrations/001_structured_index.sql` | 8 张结构化事实表，`user_version=1` | SQLite 继续作为事实源 |
| `backend/app/services/provider_runtime.py` 及现有 Provider 边界 | 受授权、预算和缓存约束的模型调用 | 固定单轮 Answer Generator，不能用于动态规划 |
| `docs/evaluation_baseline_v1.3.5.md` | 小型 PyTorch 仓库固定 30 问 | Retrieval Benchmark 问题种子 |

### 2.2 当前数据流与缺口

```text
active index version
  -> code_entities / paper_entities
  -> knowledge_edges / evidence_refs
  -> symbol_chunks
```

`symbol_chunks` 已持久化，但当前 Store 没有按 repo/active version 分页读取 Chunk、按 source/target/type 查询 Edge 或获取 Graph neighbor 的公共只读 API。Chunk 的 `metadata` 当前通常为空；`entity_type`、`qualified_name` 等过滤字段需要通过 `entity_id` 连接实体表补全。

当前没有 Qdrant、FastEmbed、sentence-transformers、FTS 检索表、向量同步记录、Retrieval Schema、检索 API 或检索指标。Python SQLite 3.53.3 已包含 FTS5，可作为零新增依赖的 Sparse baseline。

### 2.3 v1.4 必须保持的事实边界

- 结构化 SQLite 是事实源；FTS/Qdrant 是可删除、可重建的派生索引。
- 检索不得修改 Entity、Edge、Chunk、Evidence ID 或 active version。
- LLM/Reranker 输出只影响排序或回答，不回写为事实 Edge。
- unresolved edge 可展示，不得伪装为已解析 target，也不得用于无目标图遍历。
- 旧分析 JSON、报告、现有 API 和前端不依赖新检索功能。

## 3. 本阶段目标

v1.5.0 仅实现：

1. Retrieval Schema。
2. 30～50 条固定 Retrieval Benchmark、指标和消融命令。
3. Sparse Retrieval。
4. Dense Retrieval。
5. Graph Expansion。
6. 加权 RRF Fusion。
7. 可插拔 Reranker 和无模型 Mock/Identity 实现。
8. Evidence-first Context Builder。
9. 规则 Query Profile 和固定单轮 RAG 流程。
10. 检索与固定研究查询 API。
11. Dense-only、Sparse-only、Dense+Sparse、+Graph、+Reranker 消融实验。
12. FTS/Qdrant 版本化 Generation、幂等同步和隔离清理。
13. Answer Citation Validator 和 evidence-only 安全回退。

## 4. 非目标

v1.5.0 明确不实现：

- 动态 Planner、动态工具选择、Replan 或自主 Agent loop。
- Multi-Agent。
- 完整 Trace 平台或 Bad Case 前端。
- PostgreSQL、Redis、Celery、Neo4j。
- 在线训练、微调或自动生成 gold label。
- 以 LLM Judge 作为主要检索指标。
- 自动解析 v1.4 未解析的动态 Python 调用。
- 强制重写现有前端或旧报告流程。

## 5. Retrieval Schema

新增独立 `backend/app/retrieval/schemas.py`，不修改 v1.4 领域模型。所有模型使用 Pydantic v2、`extra="forbid"`、可变字段用 `default_factory`。

### 5.1 公开请求、内部查询和过滤

HTTP 请求不重复提交 URL 已包含的 `repo_id`。公开模型和内部强隔离模型分离：

```python
QueryType = Literal[
    "symbol_lookup", "implementation_explanation", "call_chain",
    "architecture", "tensor_shape", "configuration", "training_process",
    "inference_process", "paper_alignment", "general_repository",
]

class PublicRetrievalFilter(BaseModel):
    entity_types: list[str] = Field(default_factory=list)
    entity_kinds: list[Literal["code", "paper"]] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    qualified_names: list[str] = Field(default_factory=list)
    chunk_types: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)

class RetrievalSearchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    index_version_id: str | None = None
    query_type: QueryType | None = None
    filters: PublicRetrievalFilter = Field(default_factory=PublicRetrievalFilter)
    top_k: int | None = Field(default=None, ge=1, le=100)
    include_graph: bool | None = None
    include_reranker: bool | None = None

class RetrievalFilter(BaseModel):
    repo_id: str
    index_version_id: str
    entity_types: list[str] = Field(default_factory=list)
    entity_kinds: list[Literal["code", "paper"]] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    qualified_names: list[str] = Field(default_factory=list)
    chunk_types: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)

class RetrievalQuery(BaseModel):
    query_id: str
    text: str = Field(min_length=1, max_length=8_000)
    query_type: QueryType | None = None
    filters: RetrievalFilter
    top_k: int | None = Field(default=None, ge=1, le=100)
    include_graph: bool | None = None
    include_reranker: bool | None = None
```

HTTP 层把 URL `repo_id`、公开请求中的可选 version、解析到的 active version 和公开 filters 转换为内部 `RetrievalQuery`。内部 `repo_id` 和 `index_version_id` 必填，不允许跨 active 版本搜索；因此不再存在 URL repo 与 body repo 冲突分支。

### 5.2 内部阶段 Candidate

Raw、Fusion 和 Final 阶段不共用一个充满空字段的对象：

```python
class RawRetrievalHit(BaseModel):
    source: Literal["dense", "sparse", "graph"]
    chunk_id: str
    entity_id: str
    source_score: float
    source_rank: int
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

class FusedRetrievalCandidate(BaseModel):
    chunk_id: str
    entity_id: str
    hits: list[RawRetrievalHit]
    preliminary_rrf: float | None = None
    final_rrf: float | None = None
    graph_path_edge_ids: list[str] = Field(default_factory=list)

class FinalRetrievalCandidate(BaseModel):
    candidate: FusedRetrievalCandidate
    reranker_score: float | None = None
    reranker_normalized: float | None = None
    final_score: float
    contributions: dict[str, float] = Field(default_factory=dict)
```

`pre_fusion_candidates` 只设置 `preliminary_rrf`，`final_rrf=None`；`final_fusion_candidates` 必须设置 `final_rrf`。`FinalRetrievalCandidate` 的 model validator 拒绝缺少 `final_rrf` 的嵌套候选。固定内部阶段名为：`raw_dense_hits`、`raw_sparse_hits`、`pre_fusion_candidates`、`graph_seed_candidates`、`graph_candidates`、`final_fusion_candidates`。这些名称用于测试、延迟统计和后续 Trace，不作为 v1.5 动态 Agent state。

### 5.3 公开候选、分数与证据

```python
class RetrievalScore(BaseModel):
    dense: float | None = None
    sparse: float | None = None
    graph: float | None = None
    preliminary_rrf: float | None = None
    final_rrf: float
    reranker: float | None = None
    reranker_normalized: float | None = None
    final: float
    source_ranks: dict[str, int] = Field(default_factory=dict)
    contributions: dict[str, float] = Field(default_factory=dict)

class RetrievalEvidence(BaseModel):
    evidence_id: str
    source_type: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    paper_id: str | None = None
    page_number: int | None = None
    figure_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None

class RetrievalCandidate(BaseModel):
    chunk_id: str
    entity_id: str
    repo_id: str
    index_version_id: str
    entity_kind: Literal["code", "paper"]
    entity_type: str
    chunk_type: str
    path: str | None = None
    qualified_name: str | None = None
    parent_entity_id: str | None = None
    text: str
    content_hash: str
    score: RetrievalScore
    sources: list[Literal["dense", "sparse", "graph"]]
    matched_terms: list[str] = Field(default_factory=list)
    graph_path_edge_ids: list[str] = Field(default_factory=list)
    evidence: list[RetrievalEvidence] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

API 仍输出统一的 `RetrievalCandidate`，但它只能由 `FinalRetrievalCandidate` 映射产生。`contributions` 至少解释 Dense/Sparse/Graph 的 final RRF 贡献、exact boost、Hybrid 保留权重和 Reranker 归一化贡献。

### 5.4 配置、结果与上下文

```python
class RetrievalConfig(BaseModel):
    profile: QueryType
    dense_enabled: bool
    sparse_enabled: bool
    graph_enabled: bool
    reranker_enabled: bool
    dense_top_k: int = Field(ge=0, le=200)
    sparse_top_k: int = Field(ge=0, le=200)
    fusion_top_k: int = Field(ge=1, le=200)
    graph_seed_k: int = Field(ge=0, le=50)
    graph_max_hops: int = Field(ge=0, le=2)
    graph_max_candidates: int = Field(ge=0, le=100)
    final_top_k: int = Field(ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1)
    source_weights: dict[str, float]
    graph_edge_weights: dict[str, float]
    hybrid_weight: float = Field(ge=0.0, le=1.0)
    reranker_weight: float = Field(ge=0.0, le=1.0)
    dense_model_id: str | None = None
    dense_model_revision: str | None = None
    sparse_model_id: str | None = None
    reranker_model_id: str | None = None
    token_budget: int = Field(default=6_000, ge=256)
    max_entities: int = Field(default=8, ge=1, le=50)

class RetrievalResult(BaseModel):
    query: RetrievalQuery
    effective_config: RetrievalConfig
    candidates: list[RetrievalCandidate]
    total_candidates: int
    active_index_version_id: str
    vector_index_generation: str | None = None
    latency_ms: dict[str, float]
    warnings: list[str] = Field(default_factory=list)

class ContextItem(BaseModel):
    context_id: str
    entity_id: str
    chunk_ids: list[str]
    title: str
    text: str
    token_count: int
    truncated: bool
    rank: int
    relationship_notes: list[str] = Field(default_factory=list)
    evidence: list[RetrievalEvidence] = Field(default_factory=list)

class ContextBundle(BaseModel):
    repo_id: str
    index_version_id: str
    query_id: str
    items: list[ContextItem]
    estimated_tokens: int
    provider_validated_tokens: int | None = None
    token_count_method: Literal[
        "provider_tokenizer", "model_tokenizer", "conservative_code_estimate"
    ]
    token_budget: int
    omitted_candidate_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

`RetrievalConfig` 校验 `hybrid_weight + reranker_weight == 1.0`（允许浮点容差）；Reranker 关闭时配置归一为 1.0/0.0。`RetrievalResult` 是检索 API 的稳定响应边界；`ContextBundle` 是固定 RAG Answer Generator 的唯一代码/论文上下文输入。

### 5.5 Answer 与 Citation Schema

```python
class AnswerCitation(BaseModel):
    citation_id: str
    context_id: str
    evidence_id: str
    entity_id: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    paper_id: str | None = None
    page_number: int | None = None

class AnswerClaim(BaseModel):
    claim_id: str
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    supported: bool

class ResearchAnswer(BaseModel):
    answer: str
    claims: list[AnswerClaim]
    citations: list[AnswerCitation]
    unsupported_claims: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
```

模型输出只是待验证候选。`CitationValidator` 根据 `ContextBundle` 和 v1.4 Evidence 生成最终 `ResearchAnswer`，不得接受模型自行改写的路径、行号、页码或 entity/evidence 对应关系，也不得写回结构化事实数据库。

## 6. Query Profile

### 6.1 规则分类

`RuleBasedQueryProfiler` 只使用确定性规则：精确 qualified name、代码标识符、路径、中文/英文关键词和问句模式。优先级为：显式调用方 `query_type` > exact symbol/path > call chain > paper alignment > training/inference/config/tensor > architecture > implementation > general。分类结果和触发规则写入调试 metadata。

v1.5 不调用 LLM 做 Query Planning，也不根据首次结果动态改写计划。

### 6.2 默认参数矩阵

所有权重用于 weighted RRF；未列出的 edge type 不扩展。当前 v1.4 没有某类 Edge 时应返回零 Graph 候选并记录 warning，不能推造关系。

| Profile | Dense / Sparse / Graph 权重 | Edge type | Hop | Dense/Sparse Top-K | Rerank | Hybrid / Reranker 最终权重 | Context 优先级 |
| -- | -- | -- | --: | -- | -- | -- | -- |
| symbol_lookup | 0.5 / 1.5 / 0.5 | DEFINES、CONTAINS | 1 | 15 / 40 | 默认关 | 0.70 / 0.30 | exact qualified name、最窄实体 |
| implementation_explanation | 1.0 / 1.0 / 0.8 | DEFINES、CONTAINS、CALLS、INSTANTIATES | 1 | 30 / 30 | 开 | 0.35 / 0.65 | 完整函数/方法，再补依赖 |
| call_chain | 0.6 / 1.0 / 1.6 | CALLS、INSTANTIATES、DEFINES | 2 | 20 / 30 | 开 | 0.50 / 0.50 | 按调用路径顺序 |
| architecture | 1.0 / 0.7 / 1.5 | CONTAINS、DEFINES、INHERITS、INSTANTIATES、IMPORTS | 2 | 30 / 20 | 开 | 0.50 / 0.50 | repository/file/class 层次 |
| tensor_shape | 1.1 / 1.0 / 0.8 | CALLS、CONTAINS、DEFINES | 1 | 30 / 30 | 开 | 0.40 / 0.60 | shape 行和完整函数 |
| configuration | 0.6 / 1.5 / 0.7 | CONTAINS、DEFINES、IMPORTS | 1 | 15 / 40 | 默认关 | 0.70 / 0.30 | config 实体、路径和消费方 |
| training_process | 1.0 / 0.8 / 1.4 | CALLS、INSTANTIATES、CONTAINS、DEFINES | 2 | 30 / 25 | 开 | 0.50 / 0.50 | training entry 到模型/数据 |
| inference_process | 1.0 / 0.8 / 1.4 | CALLS、INSTANTIATES、CONTAINS、DEFINES | 2 | 30 / 25 | 开 | 0.50 / 0.50 | inference entry 到输出 |
| paper_alignment | 1.2 / 0.8 / 1.5 | ALIGNS_WITH、CONTAINS、DEFINES | 2 | 35 / 25 | 开 | 0.40 / 0.60 | 论文证据与对齐代码成对 |
| general_repository | 1.0 / 1.0 / 0.8 | CONTAINS、DEFINES、IMPORTS、CALLS | 1 | 30 / 30 | 开 | 0.50 / 0.50 | 多样实体、限制同文件占比 |

共同默认：`rrf_k=60`、preliminary fusion top 40、Graph seed 8、Graph 候选上限 30、final fusion top 40、Reranker 输入上限 30、最终 top 10、Context 最大 8 个实体和 6,000 tokens。Reranker 关闭或失败时强制使用 `hybrid_weight=1.0`、`reranker_weight=0.0`。调用方可以在服务端限额内覆盖，但 effective config 必须回显。

## 7. Sparse Retrieval

### 7.1 调查结论

#### SQLite FTS5

优点：当前 Python SQLite 已启用；无需新依赖、模型或网络；适合 exact symbol、qualified name、路径和英文代码 token；自动测试稳定。缺点：默认 tokenizer 对 camelCase、snake_case、点号限定名和中文/英文混合不够理想；需要显式生成可检索 symbol text；与 Qdrant Dense 候选来自不同存储。

#### Qdrant BM25 Sparse

优点：与 Dense 共用 point、payload filter 和版本隔离；Qdrant 支持 sparse vector、BM25/IDF 和多语言文本 tokenizer；生产 Hybrid 查询更统一。缺点：引入 Qdrant/FastEmbed 依赖和本地存储；首次准备稀疏模型资源、版本兼容和并发行为都需额外验收。

### 7.2 推荐方案

采用双层方案：

1. v1.5.0-b 先实现 SQLite FTS5 Baseline 和 fallback，使用独立可重建的 `data/retrieval_fts.sqlite3`，不修改 v1.4 事实表。
2. v1.5.0-c1/c2 完成 Qdrant Dense 与版本化 generation，主链路使用 FTS5 Sparse + Dense + Graph。
3. v1.5.0-c3 再将 `Qdrant/bm25` Sparse 作为可选 named vector 增强；它不可用时继续使用 FTS5，不阻塞 Dense 主链路或发布。
4. 消融报告分别记录 `fts5_sparse` 与 `qdrant_bm25_sparse`，不能把两者结果混为同一实验；只有 Locked Test 证明收益且运维条件满足后，才可把 Qdrant Sparse 设为运行配置默认值。

FTS 使用 generation 隔离，不允许查询边写边读。companion 表 `retrieval_fts_generations` 至少保存 `generation_id`、`repo_id`、`index_version_id`、`profile_hash`、`status`、`document_count`、`content_hash`、`created_at`、`activated_at` 和 `error_code`；状态为 `building`、`ready`、`stale`、`failed`、`superseded`。普通表 `retrieval_documents` 保存 generation/repo/version/chunk/entity/filter 字段，FTS5 虚表保存 `text`、拆分后的 `symbol_text`、`path_text`。

同步固定为：创建 building generation -> 在事务或隔离 staging 中写 companion/FTS rows -> count/hash 校验 -> 短事务标记 ready 并原子切换 active ready generation -> 同一 `(repo_id, index_version_id, profile_hash)` 的旧 generation 标记 superseded。active ready 唯一性也以该三元组为范围；新的结构化 index version 不会自动 supersede 旧 version 的 ready FTS generation，因此固定 Benchmark/历史查询仍可显式复现。查询只读取目标三元组的 ready generation；同步失败标记 failed，旧 ready generation 继续服务，部分 rows 永不暴露，也不修改 v1.4 事实数据库。

索引文本额外生成不替换原 Chunk：保留 qualified name 全串，同时添加 `.`、`_`、camelCase 和路径组件的空格分词形式。中文使用 SQLite `unicode61` baseline；不声称具备中文分词器级别能力，跨语言主要交给 Dense。

所有 Sparse 查询必须过滤 `repo_id`、`index_version_id`，并支持 `entity_type`、`path/path_prefix` 和 `qualified_name`。精确 symbol/path 命中在 BM25 分数之外获得固定 exact-match boost，并在 `RetrievalScore.contributions` 解释。

## 8. Dense Retrieval

### 8.1 候选模型

| 模型 | 维度 | 近似下载大小 | 语言/领域 | License | 用途 |
| -- | --: | --: | -- | -- | -- |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | 0.220 GB | 50 种自然语言，含中英文；最大序列约 128 tokens | Apache-2.0 | 默认跨语言 query embedding |
| `jinaai/jina-embeddings-v2-base-code` | 768 | 0.640 GB | 英文及约 30 种编程语言；长上下文约 8192 tokens | Apache-2.0 | 代码专用消融和可选 profile |

资料来源：FastEmbed 官方 [Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/)、[Multilingual MiniLM model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) 和 [Jina code model card](https://huggingface.co/jinaai/jina-embeddings-v2-base-code)。

### 8.2 默认选择与本地运行

默认使用多语言 MiniLM，因为验收明确包含“中文查询英文代码”，且体积和维度更小。Jina code 不作为默认中文查询模型，而作为代码标识符/英文代码问题的消融候选。

通过 `qdrant-client[fastembed]` 的 ONNX/FastEmbed 本地推理；不引入独立 sentence-transformers 服务。依赖放入可选 `retrieval` extra，旧安装和旧分析流程不强制安装。模型只允许由显式 prefetch CLI/运维步骤下载；应用启动、API 请求和自动测试不得隐式访问网络。

默认缓存目录为 `data/models`，可用 `RETRIEVAL_MODEL_CACHE_DIR` 覆盖；Qdrant Local 默认目录为 `data/qdrant`，可用 `QDRANT_LOCAL_PATH` 覆盖。离线模式设置 local-only，缺失模型返回可重试性为 false 的 `model_unavailable_offline`，并降级到 Sparse + Graph。

### 8.3 模型变化和索引失效

向量 index profile 必须记录：model ID、固定 revision、维度、距离函数、FastEmbed/ONNX 版本、文本预处理版本、Chunk schema version 和 sparse model/version。任一字段变化都生成新的 `vector_profile_hash` 和 collection generation；不得把不同维度或预处理结果写进旧 generation。

新 generation 全量或按 content hash 同步并校验后才标记 ready；查询只使用 ready generation。旧 generation 保留至显式 retention 清理。Chunk content hash 未变且 profile 相同时可复用 point；model revision 变化强制重嵌入。

## 9. Graph Retrieval

### 9.1 起始候选与实体映射

Graph seed 不直接来自某一路原始分数。执行顺序固定为：

```text
raw_dense_hits + raw_sparse_hits
→ Preliminary RRF
→ pre_fusion_candidates
→ graph_seed_candidates
→ Graph Expansion
→ graph_candidates
```

Preliminary RRF 只融合 Dense/Sparse rank，只用于选择 Graph seed，不作为最终响应排序。按 entity 聚合后取 profile 的 `graph_seed_k`；exact symbol/path boost 在 Preliminary RRF contribution 中保留，因此精确命中可以稳定进入 seed。Graph 只读取同一 `repo_id + index_version_id` 的 `knowledge_edges`。

### 9.2 扩展规则

- profile 决定允许的 edge type 和最大 hop；全局硬上限 2 hop。
- 同时支持 outgoing 和必要的 incoming 查询，例如“谁调用此函数”需要反向 CALLS。
- 每个 seed/方向/type 先按 confidence、稳定 edge ID 排序，限制 fan-out；总 Graph 候选默认 30，硬上限 100。
- 访问状态记录 entity ID 和当前最佳路径分数；相同或更低分重复路径不再扩展，防止环和高连接节点爆炸。
- targetless unresolved/ambiguous edge 不遍历。若其 source 已在候选中，可作为 relationship note 返回，明确标记 unresolved。
- Paper/Code 的 `ALIGNS_WITH` 只在目标实体存在且版本一致时遍历。

Graph 分数使用最大可信路径，不累加大量低质路径：

```text
path_score = seed_normalized_score
             * edge_type_weight
             * edge.confidence
             * (0.65 ** hop)
graph_score(entity) = max(all valid path_score)
```

### 9.3 `EntityChunkSelector`

Graph 扩展先得到 Entity，必须通过独立、确定性选择器映射回已有 `SymbolChunk`：

```python
class EntityChunkSelector(Protocol):
    def select(
        self,
        *,
        entity_id: str,
        query_text: str,
        query_profile: QueryType,
        graph_path_edge_ids: Sequence[str],
        available_chunks: Sequence[SymbolChunk],
    ) -> SymbolChunk | None: ...
```

Profile 第一优先目标：

| Profile | 首选 Chunk |
| -- | -- |
| `symbol_lookup` | canonical symbol chunk 或范围最窄的符号 Chunk |
| `implementation_explanation` | 完整 function/method Chunk |
| `call_chain` | 包含 CALLS edge evidence 行的 Chunk |
| `architecture` | class/file/model summary Chunk |
| `configuration` | config Chunk 或包含配置消费 evidence 行的 Chunk |
| `paper_alignment` | 对应论文 Chunk与代码实现 Chunk，各自作为候选 |

在 Profile 规则内或其他 Profile 下，通用稳定顺序为：

1. 包含 Graph Edge Evidence 行。
2. 包含 exact query symbol 或规范化 query term。
3. 已被当前 Dense/Sparse 命中的 Chunk，先按其 preliminary rank。
4. canonical Chunk；canonical 由 chunk type、实体范围和 ordinal 的版本化规则定义。
5. 按稳定 `chunk_id` 升序的第一项。

选择结果保存 rule、候选 IDs 和 graph path，便于解释和测试。无 Chunk 的 Entity 只生成 relationship note，不进入 Reranker，不创建或伪造文本 Chunk。

## 10. Fusion

第一版使用两次 deterministic weighted RRF，任何阶段都不直接比较 Dense cosine、BM25/FTS 或 Graph 原始分数。

### 10.1 Preliminary RRF

```text
preliminary_rrf(chunk)
  = dense_weight / (rrf_k + dense_rank)
  + sparse_weight / (rrf_k + sparse_rank)
  + exact_match_boost
```

它只消费 `raw_dense_hits` 和 `raw_sparse_hits`，产生 `pre_fusion_candidates` 和 `graph_seed_candidates`，不直接成为 API 最终输出。

### 10.2 Final Weighted RRF

```text
final_rrf(chunk) = sum(source_weight / (rrf_k + source_rank))
                    # sources = dense, sparse, graph
                   + exact_match_boost
```

- Final RRF 重新融合 `raw_dense_hits`、`raw_sparse_hits` 和经 `EntityChunkSelector` 产生的 `graph_candidates`，生成 `final_fusion_candidates`。
- `rrf_k=60`，排名从 1 开始；同分依次按 exact boost、best source rank、entity ID、chunk ID 稳定排序。
- 候选主键是 `chunk_id`，Dense/Sparse/Graph 同一 Chunk 合并；保留每个 source 的原始分数、rank 和贡献。
- 同一 Entity 多 Chunk 不直接相加：实体分取最高 Chunk 分，再给予最多 10% 的 capped multi-evidence boost，防止大文件因 Chunk 多而占优。
- 父子 Entity 同时命中时不立即删除。implementation/call/tensor profile 优先 function/method；architecture/general 优先保留 class/file 摘要，并仅在子 Chunk 提供不同证据时同时保留。
- 完全相同 `content_hash` 的父子 Chunk 只保留 profile 更合适、范围更窄的候选，其他 ID 写入去重 metadata。

### 10.3 Reranker 后的 Hybrid Fusion

Reranker 不得完全覆盖结构信号。对同一 final fusion pool 做稳定 min-max normalization；所有值相同时归一为 1.0，缺失 Reranker 分数不参与。最终分数为：

```text
final_score = hybrid_weight * normalized_final_rrf
              + reranker_weight * normalized_reranker
```

权重按 Query Profile 使用第 6 节矩阵。exact symbol boost 已进入 `final_rrf`，Graph 贡献也保留在 `final_rrf`，因此低质量 Reranker 不能完全抹掉它们。原始 Reranker 分数、归一化值、final RRF、两项最终贡献和 exact/Graph contribution 都写入 `RetrievalScore`。Reranker 关闭或失败时无损使用 final RRF 的稳定顺序。

## 11. Reranker

### 11.1 接口

```python
class Reranker(Protocol):
    def rerank(
        self,
        query: RetrievalQuery,
        candidates: Sequence[RetrievalCandidate],
        *,
        top_k: int,
    ) -> list[RetrievalCandidate]: ...
```

实现：

- `IdentityReranker`：生产回退，保持 RRF 顺序并记录 warning。
- `MockReranker`：自动测试使用固定、可注入分数。
- `FastEmbedCrossEncoderReranker`：可选真实模型实现，只处理 fusion top 30。

### 11.2 模型调查和默认行为

| 模型 | 近似大小 | 语言 | License | 结论 |
| -- | --: | -- | -- | -- |
| `BAAI/bge-reranker-base` | 1.04 GB | 中英文 | MIT | 跨语言质量候选，成本和延迟较高 |
| `Xenova/ms-marco-MiniLM-L-6-v2` | 0.08 GB | 主要英文 | Apache-2.0 | 轻量英文消融候选 |

资料来源：[FastEmbed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/) 和 [BGE reranker model card](https://huggingface.co/BAAI/bge-reranker-base)。

默认 `reranker_enabled=false`，先获得 Dense/Sparse/Graph 可解释基线。显式启用且模型已缓存时才加载；缺模型、离线、超时或推理失败使用 `IdentityReranker`，返回 warning，不让整个检索失败。真实 Reranker 只产生一个排序信号，必须按第 10.3 节与 normalized final RRF 融合，不能直接替换 `final_score`。真实模型必须记录固定 revision、输入上限和延迟，并通过 Dev 调参、Locked Test 消融证明 nDCG/MRR 收益后才考虑默认开启。

## 12. Context Builder

### 12.1 预算与选择

- 默认总预算 6,000 tokens，最多 8 个不同 Entity；API 硬上限由配置固定。
- 单个 `ContextItem` 默认最多占总 token budget 的 40%。只有其他合格候选不足时才允许超过 40%，并必须产生 `single_item_budget_override` warning。
- 优先完整 function/method，其次 class 的相关方法、file 摘要、model module，再按 profile 选择 repository/config/paper。
- 同一 entity 多 Chunk 只保留信息增益最高项；相同 content hash、文本包含关系和父子源码范围重叠均去重。
- 每个文件默认最多 3 个 ContextItem，general/architecture 可按 profile 放宽，避免单个大文件垄断。
- Paper alignment 将论文 item 和代码 item 相邻排列；其他 profile 按 final score 后再按 graph path 局部排序。

### 12.2 Token 计算和超长函数

定义 `TokenCounter` 接口，并严格区分估算与 Provider 实际校验：

- 有 Provider tokenizer 时：`token_count_method=provider_tokenizer`。
- 只有本地模型 tokenizer 时：`token_count_method=model_tokenizer`。
- 无真实 tokenizer 时：`token_count_method=conservative_code_estimate`，CJK 字符按约 1 token，ASCII/代码按 `ceil(characters / 2.5)`，最终至少 1。

Context Builder 先写 `estimated_tokens`。Provider 调用前必须再次校验完整 Prompt 实际 token、Provider context limit 和保留输出 token，并写 `provider_validated_tokens`。若超限，按 `final_score`、Profile 优先级、稳定 context ID 从最低优先级开始整项删除并重复校验；不得静默截断 Evidence ID、路径、行号或论文页码。

完整函数在单项预算内必须原样保留。超长函数采用确定性窗口：signature/docstring、匹配 query/symbol 的行及上下各 20 行、Graph edge 证据行、首尾必要控制流；合并重叠窗口并保留原行号。不得用 LLM 摘要替换证据，`truncated=true` 并列出原始范围。

### 12.3 证据和关系说明

每项标题包含 qualified name 或论文 section/figure；代码必须带规范化路径和行号，论文必须带 paper ID、页码并在可用时带 Figure/bbox。Graph note 只陈述实际 edge，例如 `A --CALLS--> B`，并带 edge ID；unresolved note 明确显示 unresolved symbol。

### 12.4 Citation Validator

Answer Generator 只能输出对 `ContextBundle` 的候选引用。Validator 执行：

1. `context_id` 必须存在于本次 ContextBundle。
2. `evidence_id` 必须存在于该 ContextItem，并能在 v1.4 Evidence 中读取。
3. `entity_id` 必须与 Evidence/Context 一致。
4. path、start/end line、paper ID 和 page number 由事实层回填，忽略模型改写值。
5. 非法 citation 被删除，关联 Claim 标记 `supported=false` 并进入 `unsupported_claims`。
6. 所有重要 Claim 均无有效证据时降低 confidence，回答改为不确定说明并返回 evidence-only 结果。
7. Validator 不修改 SQLite 事实、Edge 或 Chunk。

## 13. Retrieval Benchmark

### 13.1 数据格式

新增 JSONL，Schema 单独版本化：

```json
{
  "benchmark_schema_version": "1",
  "id": "case-001",
  "repo_id": "repo_...",
  "index_version_id": "idx_...",
  "query": "SimpleNet 的 forward 在哪里实现？",
  "query_type": "symbol_lookup",
  "split": "dev",
  "filters": {},
  "gold_entity_ids": ["ent_..."],
  "gold_chunk_ids": ["chk_..."],
  "relevant_edge_types": ["DEFINES"],
  "gold_graph_paths": [["edge_..."]],
  "difficulty": "easy",
  "tags": ["attention", "cross_language"],
  "notes": "人工依据 v1.4 事实标注"
}
```

`split` 只允许 `dev` 或 `locked_test`。Gold 固定到不可变 repo/index fixture；Test case ID 固定且 Gold 只允许人工维护。若 fixture 内容、v1.4 ID version 或 Locked Test Gold 改变，必须显式升级 benchmark schema/dataset version，不能静默重写 ID。

### 13.2 首版 40 条与固定拆分

固定为 **30 条 Development Set + 10 条 Locked Test Set**。

Development Set 用于 Query Profile、Dense/Sparse/Graph 权重、hop decay、Context 策略、Embedding 和 Reranker 模型选择。其 30 条分布为：8 exact symbol/path/config、6 implementation/tensor、6 call chain/architecture、3 training/inference、3 中文查询英文代码、3 paper alignment、1 unresolved/ambiguous 负例。

Locked Test Set 只用于最终版本验收、消融最终报告和后续版本回归，不参与日常调参。其 10 条固定覆盖：

- 2 条 exact symbol/path，其中至少 1 条 qualified name。
- 2 条中文查询英文代码。
- 2 条 Graph path，其中至少 1 条两跳或含环邻接。
- 1 条 repo/index version isolation。
- 2 条 paper alignment。
- 1 条 unresolved/ambiguous 负例。

复用现有 30 问中的事实，但增加至少两个固定仓库 fixture，确保 repo/version 隔离、同名符号、Graph 环和论文路径可测。Gold 由人工核对 Entity/Chunk/Edge，不由待评测检索器或 LLM 自动生成。未来增加 repository-level holdout，但不作为 v1.5 DoD。

### 13.3 指标

- Recall@1、Recall@5、Recall@10：任一 gold chunk/entity 命中；同时分别报告 chunk recall 和 entity recall。
- MRR：首个相关候选 rank 的倒数。
- nDCG@5、nDCG@10：支持 gold relevance 1～3；首版未分级时按 binary relevance。
- Graph Path Recall：gold path 的 edge ID 序列是否在返回 graph paths 中；另报 edge-type recall。
- 平均、P50、P95 检索延迟，拆分 profile/sparse/dense/graph/fusion/rerank/context。
- 失败率和 fallback 次数。

消融固定运行：Sparse only、Dense only、Dense+Sparse（Preliminary/Final RRF 无 Graph）、Dense+Sparse+Graph（Preliminary RRF -> Graph -> Final RRF）、全部+Reranker Hybrid Fusion。Qdrant BM25 Sparse 作为额外可选消融，与 FTS5 Sparse 分开报告，不阻塞主链路。报告必须分别展示 Dev 和 Locked Test 指标，最终结论以 Locked Test 为主，并包含相同 benchmark/version、机器/模型信息、冷/热缓存状态和每阶段参数；不以 LLM Judge 代替上述指标。

## 14. 数据库和向量存储

### 14.1 存储职责

- `data/structured_index.sqlite3`：唯一结构化事实源，现有 8 张 v1.4 表不被向量数据替代。
- `data/retrieval_fts.sqlite3`：可重建 FTS5 Sparse baseline/fallback，包含 generation、documents 和 FTS rows；查询只读取 active ready generation。
- `data/qdrant`：Qdrant Local Dense/Sparse point。
- `data/retrieval/manifests/{repo_id}/{index_version_id}/{profile_hash}.json`：原子写入的同步 Manifest，记录计数、模型 revision、collection、状态和校验结果。

不要求 v1.4 事实数据库与 Qdrant 跨库事务。同步顺序是建立新 generation -> 写 points -> count/sample 校验 -> 原子写 ready manifest；查询只读取 ready manifest。失败 generation 不影响旧 ready generation。

### 14.2 Collection 与 Point

Collection 基础命名为 `cra_chunks_v1_{vector_profile_hash前12位}`。Manifest 和 Collection metadata 必须保存完整 `vector_profile_hash` 及完整 profile payload。打开已存在 Collection 时必须校验完整 hash/profile；若前 12 位相同但完整 hash 不同，自动增加使用的 hash 长度，仍冲突时追加由完整 hash 确定的稳定后缀。不得只根据 Collection 名称认定 profile 一致。相同完整 vector profile 可跨 repo/version 共用 collection，所有查询强制 payload filter；模型/维度/预处理变化创建新 collection。

named vectors：

- `dense`：profile 指定的 Dense 模型维度和 cosine distance。
- `sparse_bm25_v1`：仅 v1.5.0-c3 generation 启用的可选 Qdrant BM25/IDF sparse vector。

Qdrant point ID 必须包含完整 profile、repository、index version 和 Chunk 身份：

```python
point_id = uuid5(
    CRA_RETRIEVAL_NAMESPACE,
    f"{vector_profile_hash}:{repo_id}:{index_version_id}:{chunk_id}",
)
```

因此不同 repository 或 index version 中相同稳定 `chunk_id` 可同时存在，superseded 版本仍可被固定 Benchmark 和历史查询复现。原始 `chunk_id` 继续保存在 payload。Payload 至少包含：

```text
repo_id, index_version_id, chunk_id, entity_id, entity_kind,
entity_type, chunk_type, path, qualified_name, parent_entity_id,
content_hash, ordinal, start_line, end_line, index_schema_version
```

为 repo_id、index_version_id、entity_type、entity_kind、chunk_type、path 和 qualified_name 建立 keyword/payload index。查询过滤必须同时包含 repo 和 version。

### 14.3 同步、重建和删除

- 同 `vector_profile_hash + repo_id + index_version_id + chunk_id` 重复同步定位同一 Point，再以 content hash 判断是否跳过或更新，计数不增长。
- content hash 改变时只更新该 repo/version 的 UUID point；已从该 version snapshot 删除的 Chunk 只删除该 version 对应 Point。
- 新 index version 独立同步，不覆盖 superseded version；active 变化后查询默认解析新 active 并要求其 ready vector manifest。
- 删除旧 index version 顺序：停止新查询引用 -> 使用 `repo_id + index_version_id + vector_profile_hash` 精确过滤并删除对应 Qdrant Points -> 删除该 version 的 FTS generation/rows -> 删除 retrieval manifest；不得覆盖或删除其他 version/repository 的 Point，结构化事实 retention 由 v1.4 单独控制。
- 若向量与 SQLite 计数/hash 不一致，generation 标记 stale，API 返回明确 warning 或降级 Sparse FTS，不跨版本补齐。

### 14.4 Feature Flag 和 Server 边界

- 三个新路由始终注册，保持 OpenAPI 与客户端 contract 稳定。`RETRIEVAL_ENABLED=false` 时不执行检索，稳定返回 HTTP 503 和 `retrieval_disabled`。
- `RETRIEVAL_DENSE_ENABLED=false`、`RETRIEVAL_RERANKER_ENABLED=false` 默认不加载模型。
- `RETRIEVAL_OFFLINE=true` 时禁止下载。
- `VectorStore` Protocol 隔离 `QdrantLocalVectorStore`；以后切换 Qdrant Server 只替换 client/config，不改变 Retrieval Service、Schema、point/payload 语义。
- Qdrant Local 按单进程本地开发定位；同步使用进程内 repo/profile 锁。需要多进程写入时必须切换 Qdrant Server，不声称 Local path 支持任意并发 writer。

## 15. API 设计

v1.5.0-f 新增但不改变现有分析 API：

### 15.1 `POST /repositories/{repo_id}/retrieval/search`

请求体使用 `RetrievalSearchRequest`：query text、可选 explicit `index_version_id`、query type、公开 filter、top-k 和受限 config overrides，不含 `repo_id`。HTTP service 将 URL repo 与请求转换为完整内部 `RetrievalQuery`；若未给 version，解析该 repo 当前 active version，响应中始终返回最终 version。

响应：`RetrievalResult`。不调用答案 LLM，可在 Dense/Reranker 不可用时按配置降级并返回 warnings。

### 15.2 `POST /repositories/{repo_id}/research/query`

固定流程：profile -> retrieval -> context builder -> Provider token validation -> 单次 Answer Generator -> Citation Validator。请求包含 query、可选 version/config 和 `answer_enabled`，不在 body 重复 repo ID。启用回答必须复用现有 Provider 授权、预算、缓存和脱敏边界；不允许 Agent tool loop。

响应包含经 Validator 处理的 `ResearchAnswer`、`RetrievalResult` 摘要、`ContextBundle`、provider usage 和 warnings。非法引用被删除，unsupported Claim 显式暴露；所有重要引用均非法时降置信度并返回 evidence-only 结果。Provider 未授权/不可用或 `answer_enabled=false` 时同样返回成功的 evidence-only 结果，不丢失检索与上下文。

### 15.3 `GET /repositories/{repo_id}/retrieval/config`

返回 active index version、effective feature flags、profile defaults、Dense/Sparse/Reranker model ID/revision、模型缓存就绪状态、vector generation/status 和限额；不返回 token、绝对敏感路径或 Provider secret。

### 15.4 错误结构

沿用项目结构化错误语义：

```json
{
  "error": {
    "error_code": "vector_index_not_ready",
    "component": "retrieval",
    "message": "...",
    "retryable": true,
    "context": {"repo_id": "...", "index_version_id": "..."}
  }
}
```

稳定 error code：`repository_not_found`、`index_version_not_found`、`index_version_not_active`、`retrieval_disabled`、`vector_index_missing`、`vector_index_stale`、`model_unavailable_offline`、`retrieval_busy`、`invalid_retrieval_filter`。所有新路由在 flag 关闭时返回 503 `retrieval_disabled`；公开 body 不包含 repo ID，绝不放宽为跨 repo 搜索。

## 16. 推荐目录和文件边界

### 16.1 新增

```text
backend/app/retrieval/
  schemas.py
  query_profiler.py
  sparse_retriever.py
  dense_retriever.py
  graph_retriever.py
  entity_chunk_selector.py
  fusion.py
  reranker.py
  context_builder.py
  citation_validator.py
  retrieval_service.py
  embedder.py
  vector_store.py
  sync_service.py
backend/app/persistence/retrieval_read_store.py
backend/app/persistence/fts_generation_store.py
backend/app/services/research_query_service.py
tests/retrieval/
tests/fixtures/retrieval/
evaluation/retrieval/
scripts/evaluate_retrieval.py
```

### 16.2 修改

| 文件/区域 | 作用 | 约束 |
| -- | -- | -- |
| `pyproject.toml` | 增加可选 `retrieval` extra 和版本固定 | 不影响默认旧安装 |
| `backend/app/main.py` | v1.5.0-f 注册三个新路由 | 不改现有路由行为 |
| `backend/app/services/analysis_options.py` | 增加检索独立配置读取 | 不把检索节点插入旧 LangGraph |
| README/docs | 安装、prefetch、离线、评测和清理说明 | 不宣称未测能力 |

`StructuredIndexStore` 只在确有共用价值时增加只读方法；首选独立 `RetrievalReadStore`，避免检索 SQL 污染写入状态机。

### 16.3 禁止修改

- v1.4 Entity/Edge/Evidence/Chunk 字段和 ID 算法。
- `backend/app/agents/graph.py` 的现有节点和顺序。
- 旧 JSON/报告生成逻辑。
- 整个 `frontend/`。
- 现有结构化事实表的含义；检索缓存不得成为事实源。

## 17. 分阶段实施

### v1.5.0-a：Schema、Read Store、Dev/Test Benchmark 与指标

- 输入：v1.4 领域模型、真实 sample index、现有固定 30 问。
- 输出：公开请求/内部查询 Schema、Raw/Fused/Final Candidate、只读 Store、30 Dev + 10 Locked Test、指标与全 Mock runner。
- 修改文件：新增 `backend/app/retrieval/schemas.py`、`retrieval_read_store.py`、`evaluation/retrieval/`、`tests/retrieval/` 和评测脚本。
- 新增依赖：无。
- 测试：Schema 校验、public-to-internal 转换、active/version/repo 隔离、split/gold ID 完整性、指标公式和稳定排序。
- 验收：30 Dev + 10 Locked Test 均能解析且 gold ID 存在；Locked Test 覆盖规定的六类场景；Mock 排名的 Recall/MRR/nDCG/Graph Path Recall 与手算一致；自动测试无网络。
- 回滚点：删除新增 retrieval/benchmark 文件，不影响 v1.4。

### v1.5.0-b：FTS5 Sparse、FTS Generation 与 exact symbol/path

- 输入：active SymbolChunk + Entity metadata。
- 输出：FTS5 generation 状态机、原子 ready 切换、exact symbol/path boost、过滤和 Sparse candidate。
- 修改文件：新增 sparse retriever、FTS generation store/sync、专项测试；不改事实 migration。
- 新增依赖：无，使用标准库 sqlite3/FTS5。
- 测试：snake/camel/dotted symbol、中文文本 baseline、repo/version/path/type filter、building/ready/failed/superseded、失败保留旧 ready、重复同步、删除 version、无 FTS5 明确错误。
- 验收：exact symbol Dev 与 Locked Test Recall@5=100%；查询永不读取 building/failed generation；失败同步不影响旧 ready；同 repo 不同版本和不同 repo 零串扰；重复同步计数/hash 稳定。
- 回滚点：关闭 Sparse flag并删除可重建 `retrieval_fts.sqlite3`。

### v1.5.0-c1：Dense Provider、Fake Embedder、VectorStore 与 Qdrant Dense

- 输入：SymbolChunk、vector profile、已显式缓存的 Dense 模型。
- 输出：`Embedder` Protocol、Fake Embedder、`VectorStore` Protocol、Qdrant Local Dense adapter 和 vector profile hash。
- 修改文件：`embedder.py`、`dense_retriever.py`、`vector_store.py`、配置、可选依赖和测试。
- 新增依赖：可选 `qdrant-client[fastembed]`，版本固定；默认安装不强制。
- 测试：Fake Embedder、维度/模型 profile 校验、filter 转换、缺模型/离线 fallback；自动测试不下载模型，真实模型仅显式 marker。
- 验收：Dense raw hits 可经同一 Protocol 在 Fake/Qdrant adapter 间切换；profile 完整可复现；模型缺失时 FTS5 + Graph 主链路可继续。
- 回滚点：关闭 Dense flag，保留 FTS5；卸载可选 retrieval extra 不影响旧系统。

### v1.5.0-c2：Vector Generation、版本同步、幂等和清理

- 输入：c1 VectorStore、完整 vector profile、repo/index version 的 SymbolChunk 快照。
- 输出：ready/stale/failed generation Manifest、版本化 Point ID、幂等 upsert、active 隔离、retention/删除。
- 修改文件：`sync_service.py`、vector manifest/collection resolver、retention service 和专项测试。
- 新增依赖：无新增，复用 c1 可选依赖。
- 测试：相同 chunk 跨 version/repo 不覆盖、单 version 删除隔离、模型 revision/dim 新 generation、短 hash collision、部分写/校验失败、重复同步。
- 验收：Point ID 严格使用完整 profile/repo/version/chunk；superseded version 可复现；Collection 完整 hash/profile 校验通过后才复用；失败 generation 不激活。
- 回滚点：查询切回上一 ready generation，删除未 ready generation，不修改 v1.4 事实。

### v1.5.0-c3：可选 Qdrant BM25 Sparse

- 输入：c2 generation/sync、同一 Chunk payload、Qdrant BM25 sparse adapter。
- 输出：`sparse_bm25_v1` named vector 和独立消融配置。
- 修改文件：Qdrant sparse adapter、sync profile、配置和专项测试。
- 新增依赖：无新增，复用 `qdrant-client[fastembed]` optional extra。
- 测试：Sparse named vector、payload filter、同 Point 多向量同步、缺资源 fallback 和与 FTS5 分开计分。
- 验收：Qdrant BM25 可单独消融；不可用时自动使用 FTS5，不阻塞 FTS5 + Dense + Graph 主链路或 v1.5 发布。
- 回滚点：关闭 Qdrant Sparse flag，保留 Dense points 和 FTS5。

### v1.5.0-d：Preliminary RRF、Graph Seed、Graph Expansion、EntityChunkSelector 与 Final RRF

- 输入：`raw_dense_hits`、`raw_sparse_hits`、同版本 KnowledgeEdge 和 Entity 的可用 SymbolChunk。
- 输出：`pre_fusion_candidates`、`graph_seed_candidates`、一/二跳 `graph_candidates`、确定性 Entity-to-Chunk 选择、`final_fusion_candidates` 和两阶段分数解释。
- 修改文件：query profiler、graph retriever、`entity_chunk_selector.py`、fusion 和测试。
- 新增依赖：无。
- 测试：Preliminary RRF 只含 Dense/Sparse、seed 稳定性、入/出边、一/二跳、环、多路径、fan-out cap、unresolved、跨 repo/version、edge evidence/canonical/no-chunk selector、Final RRF tie-break 和父子冲突。
- 验收：不能直接比较原始分数；Preliminary RRF 不作为最终输出；循环图终止且候选不超限；targetless edge 不遍历；Entity-to-Chunk 可解释且重复运行一致；Graph Path Recall 可计算。
- 回滚点：`graph_enabled=false`，Final RRF 只融合 Dense+Sparse；Preliminary 与 Final 仍保持独立阶段。

### v1.5.0-e：Reranker 融合、Context Builder 和两阶段 Token 预算

- 输入：final fusion candidates、Evidence/Entity/Edge、Query Profile Hybrid/Reranker 权重和 token budget。
- 输出：Reranker Protocol/Mock/Identity/可选 FastEmbed、保留 final RRF 的 profile-aware 融合、带 estimated/provider validated token 的 ContextBundle。
- 修改文件：reranker、context builder、模型配置及测试。
- 新增依赖：复用 v1.5.0-c1 FastEmbed extra，不再新增基础依赖。
- 测试：bad Reranker 下 exact symbol 保留、RRF/Reranker contribution、失败回退、保守代码估算、单 Item 40% 限额、Provider 复验确定性删减、完整函数/超长窗口、父子 Chunk 和证据。
- 验收：Reranker 不完全覆盖 exact/Graph/RRF；失败无损返回 final RRF 顺序；Context 区分 estimated/validated tokens，不超 Provider 限制，整项删减不破坏 evidence；自动测试不加载真实模型。
- 回滚点：关闭 Reranker；Context Builder 可继续消费 RRF。

### v1.5.0-f：固定 RAG API、Citation Validator、消融实验和文档

- 输入：Retrieval Service、ContextBundle、现有受控 Provider runtime。
- 输出：始终注册的三个 API、固定单轮回答、Citation Validator、Dev/Locked Test 五组主消融和可选 Qdrant Sparse 消融、安装/离线/清理文档。
- 修改文件：`main.py`、research query service、`citation_validator.py`、API tests、README/evaluation docs。
- 新增依赖：无新增；复用可选 retrieval extra。
- 测试：public request/internal query、active version、503 flag off、Citation 存在性和不可改行号、unsupported Claim、全非法引用 evidence-only、Provider mock、旧 API 回归和完整验收。
- 验收：30 Dev + 10 Locked Test 五组主消融全部可复现并分开报告，主要结论以 Locked Test 为准；Citation 只能引用 Context 真实 Evidence；报告 Recall@K/MRR/nDCG/Graph Path Recall/延迟；无 LLM Judge 主指标；旧后端/前端/validate 全通过。
- 回滚点：关闭 `RETRIEVAL_ENABLED` 后新路由保留并返回 503；旧分析和索引不受影响。

## 18. 测试计划

| 场景 | 建议测试文件/Fixture | 关键断言 |
| -- | -- | -- |
| exact symbol lookup | `test_sparse_retriever.py` / small_pytorch | qualified name/path Recall@5=100% |
| 中文查询英文代码 | `test_dense_retriever.py` + fake bilingual vectors；手动真实模型 marker | 自动测试无下载，模型验收单独记录 |
| repo/index 隔离 | `test_retrieval_read_store.py` / two_repos_two_versions | 所有候选严格同 repo/version |
| 两阶段 RRF | `test_fusion.py` | Preliminary 只融合 Dense/Sparse；Final 才融合 Graph；不直接比较 raw scores |
| Dense/Sparse 去重 | `test_fusion.py` | 同 chunk 一条候选且来源、preliminary/final 分数完整 |
| Graph 一跳/两跳 | `test_graph_retriever.py` / graph_repo | path、hop 和 edge type 正确 |
| Graph 环 | 同上 / cyclic_calls | 有限终止、稳定排序、无重复扩散 |
| unresolved edge | 同上 / unresolved_calls | 不遍历，无假 target，可作为 note |
| EntityChunk edge evidence | `test_entity_chunk_selector.py::test_graph_entity_selects_edge_evidence_chunk` | 优先包含关系证据行 |
| EntityChunk canonical | `test_entity_chunk_selector.py::test_graph_entity_selects_canonical_chunk_deterministically` | 无更高优先级时稳定选择 canonical/最小 chunk ID |
| Entity 无 Chunk | `test_entity_chunk_selector.py::test_graph_entity_without_chunk_becomes_note_only` | 仅 relationship note，不进 Reranker |
| RRF 稳定性 | `test_fusion.py` | preliminary/final tie-break、权重、重复运行一致 |
| exact 对抗坏 Reranker | `test_reranker.py::test_exact_symbol_survives_bad_reranker_score` | exact Hybrid 信号不被完全抹掉 |
| Reranker 贡献解释 | `test_reranker.py::test_reranker_and_rrf_contributions_are_explained` | raw/normalized/final contribution 完整 |
| Reranker 回退 | `test_reranker.py::test_reranker_failure_preserves_final_rrf_order` | 缺模型/异常无损保留 final RRF 顺序 |
| Token 估算 | `test_context_builder.py::test_code_token_estimate_is_conservative` | CJK 与 ASCII/代码估算不低于固定基准 |
| 单 Item 限额 | `test_context_builder.py::test_single_context_item_does_not_monopolize_budget` | 默认不超过总预算 40%，例外有 warning |
| Provider Token 复验 | `test_context_builder.py::test_provider_validation_reduces_context_deterministically` | 超限按稳定低优先级整项删除，不破坏 evidence |
| 模型版本变化 | `test_vector_sync.py` | profile hash/collection generation 变化 |
| 向量重复同步 | 同上 | point count 和 UUID 稳定 |
| 同 Chunk 跨版本 | `test_vector_sync.py::test_same_chunk_id_across_versions_does_not_overwrite` | 两个版本 Point ID 不同且可同时查询 |
| 同 Chunk 跨仓库 | `test_vector_sync.py::test_same_chunk_id_across_repositories_isolated` | 两个 repo Point ID 不同且 payload 隔离 |
| 删除单一 version | `test_retrieval_retention.py::test_delete_one_version_keeps_other_versions` | 仅目标 version points/FTS/manifest 删除 |
| Collection 短 Hash 冲突 | `test_vector_sync.py::test_collection_short_hash_collision_is_detected` | 校验完整 hash 并扩展名称/稳定后缀 |
| FTS 失败同步 | `test_fts_generation.py::test_failed_fts_sync_keeps_previous_ready_generation` | 旧 ready 继续服务 |
| FTS building 隔离 | `test_fts_generation.py::test_query_never_reads_building_fts_generation` | 查询不暴露部分 rows |
| FTS 幂等 | `test_fts_generation.py::test_repeated_fts_sync_is_idempotent` | active generation/count/hash 稳定 |
| Citation 存在性 | `test_citation_validator.py::test_generated_citation_must_exist_in_context` | 非 Context 引用被删除 |
| Citation 行号防改写 | `test_citation_validator.py::test_model_cannot_change_evidence_line_range` | 路径/行号/页码从事实回填 |
| unsupported Claim | `test_citation_validator.py::test_unsupported_claim_is_exposed` | Claim 标记 unsupported 并暴露原因 |
| 全非法 Citation | `test_citation_validator.py::test_all_invalid_citations_fall_back_to_evidence_only` | 降置信度并 evidence-only |
| 无模型/无网络/离线 | `test_retrieval_fallback.py` | 不发网络请求，Sparse/Graph 仍可用 |
| Qdrant Local busy/并发 | `test_vector_sync.py` | repo/profile 锁、有限 retry、无部分 ready |
| FTS/Qdrant 与 SQLite 不一致 | `test_sync_consistency.py` | stale 标记、降级、绝不跨版本补齐 |
| API/Feature Flag | `test_retrieval_api.py` + 现有 API tests | 新路由始终存在，flag off 稳定返回 503，旧响应不变 |
| Benchmark split | `test_retrieval_benchmark.py` | 30 Dev + 10 Locked，Locked 覆盖六类要求且不参与调参 |

自动测试通过依赖注入使用 FakeEmbedder、FakeVectorStore、MockReranker 和 Mock Provider；任何测试都不得下载真实模型。真实 Qdrant Local/模型测试使用显式 marker 和预缓存目录，CI 默认跳过并单独记录。

## 19. 风险与缓解

| 风险 | 影响 | 缓解 |
| -- | -- | -- |
| 中英文跨语言检索 | 中文 query 无法命中英文代码 | 默认多语言 Dense；固定跨语言 benchmark；Sparse 只作互补 |
| 代码符号分词 | camel/snake/dotted/path 被拆错 | 原串 + 规范拆分双字段、exact boost、symbol lookup profile |
| 模型首次下载 | 启动慢、离线失败、供应链不确定 | 显式 prefetch、固定 revision、禁止请求时下载、Sparse fallback |
| 模型 License | 发布或商用限制变化 | 记录 model card/revision/license，发布前再次法务核验 |
| Embedding 模型切换 | 向量维度/语义混用 | profile hash + 新 collection generation，禁止原地混合 |
| Qdrant Local 并发 | 多进程写冲突或损坏 | 单进程锁；多 writer 切 Server adapter；ready manifest 隔离 |
| Qdrant Point 版本覆盖 | 稳定 chunk ID 在版本间互相覆盖 | Point UUID 包含完整 profile/repo/version/chunk；跨版本/仓库隔离测试 |
| Collection 短 Hash 碰撞 | 错误复用不兼容向量 Schema | 保存并校验完整 hash/profile，冲突时扩展名称或稳定后缀 |
| FTS 部分同步 | 查询暴露不完整候选 | building/ready generation、count/hash 校验和原子 active 切换 |
| 大仓库索引时间 | embedding 和 upsert 过慢 | content hash 增量、批处理、阶段延迟指标、可取消 staging |
| Chunk 粒度 | file/class 重复淹没精确函数 | entity 聚合、父子去重、profile 优先级、Context 限额 |
| Graph 噪声扩散 | 高度节点导致召回污染 | edge allowlist、confidence、hop decay、fan-out/总数 cap |
| Reranker 延迟 | 单次查询过慢 | 默认关闭、仅 top 30、超时回退、单独 P95 指标 |
| Qdrant 与 SQLite 不一致 | 返回不存在或错误版本事实 | ready/stale manifest、双重 version filter、count/hash 校验 |
| 评测集规模、偏差与过拟合 | 40 条不能代表真实仓库或被反复调参污染 | 固定 30 Dev + 10 Locked Test、分开报告、Test 不调参；未来增加 repo holdout |
| Active version 切换竞态 | 查询中途混合两个版本 | 请求开始解析并固定 version，全链路显式传递 |
| unresolved 动态调用 | Call chain 不完整 | 展示缺口、Graph 指标区分已解析/未解析，不用模型伪造边 |
| Paper fixture 不足 | paper_alignment 无真实衡量 | 固定小 PDF/解析快照和人工 gold，避免依赖在线论文 |

## 20. Definition of Done

v1.5.0 完成必须同时满足：

1. 公开 API Request、内部 RetrievalQuery、Raw/Fused/Final Candidate、Retrieval/Context/Answer/Citation Schema 均有 JSON round-trip、边界校验和 OpenAPI 测试。
2. 固定 40 条 benchmark 明确拆分为 30 Dev + 10 Locked Test；Test ID 固定、Gold 人工维护且不参与调参，修改须升级 benchmark version。
3. Locked Test 覆盖 exact symbol、中文查询英文代码、Graph path、repo/version isolation、paper alignment 和 unresolved 负例；最终报告同时展示 Dev/Test，主要结论以 Locked Test 为准。
4. Sparse exact symbol 的 Dev 与 Locked Test Recall@5=100%，repo/index 隔离测试零串扰。
5. FTS generation 具备 building、ready、stale、failed、superseded；查询永不读取 building/failed，失败同步保留旧 ready，重复同步幂等。
6. Dense 默认模型和 Jina code 消融记录 model ID、revision、dimension、license、缓存状态与真实 Recall/延迟；自动 CI 不下载模型。
7. Qdrant Point UUID 包含完整 `vector_profile_hash + repo_id + index_version_id + chunk_id`；同 chunk 在不同 repo/version 可同时存在且不覆盖。
8. 删除某一 index version 只删除该 repo/version/profile 的 Points 和 FTS generation，其他 repository/version 及 superseded Benchmark 快照仍可复现。
9. Collection Manifest/metadata 保存并校验完整 profile hash；前 12 位碰撞能自动检测并通过扩展 hash 长度或稳定后缀隔离。
10. 检索严格执行 `raw_dense_hits/raw_sparse_hits -> Preliminary RRF -> Graph seed -> Graph Expansion -> Final RRF`；禁止直接比较 Dense、BM25/FTS 和 Graph 原始分数。
11. Graph 一/二跳、环、fan-out、unresolved 和跨版本均通过；`EntityChunkSelector` 按 evidence/query/current-hit/canonical/stable-ID 规则确定映射，无 Chunk 实体只生成 note。
12. Preliminary/Final Weighted RRF 的去重、贡献解释和 tie-break 完全确定；同输入重复运行顺序一致，Graph Path Recall 可复现。
13. Reranker 默认关闭；启用时按 Profile 融合 normalized final RRF 与 normalized Reranker，不能完全覆盖 exact symbol、Graph 或 Hybrid 信号。
14. Reranker 原始分数、归一化值和最终贡献可解释；缺失、超时和异常均无损回退到 final RRF 顺序。
15. ContextBundle 区分 `estimated_tokens` 与 `provider_validated_tokens` 并记录 method；保守代码估算、Provider context limit 和输出 token reserve 均有测试。
16. 单个 ContextItem 默认不超过总预算 40%；候选不足时的例外必须有 warning；Provider 超限时确定性整项删除且不破坏 Evidence ID/行号。
17. Context 完整函数优先，父子/重复 Chunk 去重，所有 item 有路径行号或论文页码证据。
18. Citation Validator 只接受 ContextBundle 中真实 context/evidence/entity 关系；模型不能改写路径、行号或页码，非法引用和 unsupported Claim 显式暴露。
19. 所有重要 Citation 非法时降低 confidence 并返回 evidence-only；Validator 不写回 v1.4 事实数据库。
20. FTS/Qdrant 任一派生索引失败或 stale 时不修改 SQLite 事实和旧 active index，并返回明确降级/错误信息。
21. 三个新路由始终注册；`RETRIEVAL_ENABLED=false` 时稳定返回 HTTP 503 `retrieval_disabled`，固定 research query 无动态 planning/tool loop。
22. 五组主消融分别在 Dev 和 Locked Test 输出 Recall@1/5/10、MRR、nDCG@5/10、Graph Path Recall、平均/P50/P95 延迟和 fallback 率；Qdrant BM25 Sparse 作为可选额外消融，不阻塞 Dense 主链路和 v1.5 DoD。
23. 完整 `python -m pytest -q`、前端测试、前端 build 和 `scripts/validate.sh` 全部通过，真实结果写入 v1.5 验收文档。
24. v1.4 Entity/Edge/Chunk/Evidence ID、旧 JSON、报告、API 和前端保持 Schema 与规范化语义兼容。

本文件只定义后续实施方案；本轮审计不实现任何 Dense、Sparse、Graph、Fusion、Reranker、Context Builder、检索 API 或固定 RAG 功能。
