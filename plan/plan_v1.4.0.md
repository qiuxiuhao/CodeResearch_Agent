# CodeResearch Agent v1.4.0 结构化索引基础开发计划

状态：开工前设计冻结  
基线：v1.3.5 / `5073f9f899e83759a6e21ec1ea56a7ae282f84eb`  
计划范围：v1.4.0-a 至 v1.4.0-e

## 1. 背景

v1.3.5 已能从仓库扫描、Python AST、文件/函数/模型规则和论文解析中产生大量确定性事实，但这些事实分散在 `AgentState` 和多个任务级 JSON 中。内部调用仍主要以 `raw_call_expressions` 或启发式字符串保存，跨文件 import、符号身份、关系、证据、版本和清理没有统一表达。

这种结构可以支撑当前报告和教学展示，但不能稳定支撑后续的代码结构感知检索、图扩展和证据引用。v1.4.0 因此只建立确定性结构化索引基础：将已有事实增量转换为统一实体、关系、证据和 Symbol-aware Chunk，并提供可迁移、幂等、可回滚的 SQLite 快照持久化。

本阶段不推倒重写旧分析流程。新索引作为影子产物接入，旧 JSON、报告和前端仍以原有数据流工作。

## 2. 当前代码事实

### 2.1 当前相关文件

| 路径 | 关键职责 |
| -- | -- |
| `backend/app/agents/graph.py` | 定义 21 个 LangGraph 节点和相同顺序的 `_SequentialGraph` fallback |
| `backend/app/schemas/state.py` | 定义当前共享 `AgentState` |
| `backend/app/schemas/code.py` | 定义 `ImportInfo`、`FunctionInfo`、`ClassInfo`、`ParsedFile` |
| `backend/app/tools/repo_scan_tool.py` | 扫描仓库并识别 Python/入口/模型/训练/推理/配置候选 |
| `backend/app/tools/ast_parse_tool.py` | 使用 Python AST 提取 import、alias、class、function、method、行号和调用表达式 |
| `backend/app/tools/file_analyze_tool.py` | 基于路径和 AST 事实确定性分类文件 |
| `backend/app/tools/library_call_extractor_tool.py` | 结合 alias 和项目符号排除内部调用、识别库函数调用 |
| `backend/app/tools/function_analyze_tool.py` | 生成函数用途、输入输出、计算逻辑和启发式内部调用列表 |
| `backend/app/tools/model_detect_tool.py` | 重解析 `__init__`/`forward`，提取模型层和基础数据流 |
| `backend/app/tools/paper_parse_tool.py` | 解析论文标题、Section、贡献点、关键词和模块名 |
| `backend/app/tools/paper_figure_extract_tool.py` | 本地提取 Figure 页码、bbox、caption、资产和稳定 Figure ID |
| `backend/app/tools/paper_code_align_tool.py` | 以规则将论文贡献对齐到文件、类、函数和模型模块候选 |
| `backend/app/agents/nodes/report_generate_node.py` | 统一保存旧 JSON 并生成 `report.md` |
| `backend/app/services/analysis_service.py` | 初始化分析、调用 Graph、读取任务结果和生成摘要 |
| `backend/app/services/library_function_service.py` | 管理全局库函数 SQLite 知识库 |
| `frontend/src/types/analysis.ts` | 定义旧任务结果的前端消费类型 |

### 2.2 当前 Schema

- `ImportInfo` 保存 `module`、`name`、`alias`、`import_type`、`line_no`；相对导入级别编码在 module 的前导 `.` 中。
- `FunctionInfo` 保存文件、函数名、所属类、参数、起止行、源码和 `raw_call_expressions`。
- `ClassInfo` 保存文件、类名、基类、起止行和直接方法名。
- `ParsedFile` 聚合 imports、aliases、classes、functions 和 errors。
- `FileAnalysis`、`FunctionAnalysis`、`ModelAnalysis` 是规则分析结果，可直接作为索引构建输入。
- `PaperAnalysis`、`PaperSection`、`PaperContribution`、`PaperFigure` 提供论文页码、文本、Figure/bbox 和证据输入。
- `PaperCodeTarget` 是旧规则对齐目标，不具备统一实体身份，不能直接替代 `CodeEntity`。

### 2.3 当前数据流

```text
ZIP
→ unzip
→ repo_scan
→ code_parse
→ file/library/function/model rule analysis
→ optional paper parse/Figure extract/rule alignment
→ optional LLM/VLM explanations
→ diagram/teaching diagram/library docs
→ report_generate
→ task JSON + report.md
```

`raw_call_expressions` 由 `ast_parse_tool._AstCollector` 遍历函数内 `ast.Call` 产生。库调用、函数分析和模型分析会消费调用信息，但当前没有仓库级 Symbol Table、Import Resolver 或 Call Graph。

### 2.4 当前持久化方式

- 分析产物按任务写入 `outputs/{task_id}`，主要是 JSON、Markdown 和图片资产。
- API 每次从任务目录读取旧结果，不依赖仓库数据库。
- `data/python_function_library.sqlite3` 只保存全局库函数教学说明。
- LLM、Vision、Image Generation 和 Teaching Review 使用各自 SQLite 缓存。
- 当前 SQLite 通过 `CREATE TABLE IF NOT EXISTS` 延迟建表，实际数据库 `PRAGMA user_version=0`，没有编号 migration。

### 2.5 当前测试覆盖

- AST、仓库扫描、文件/函数/模型规则、库函数 alias、论文解析/Figure/对齐均有单元测试。
- `test_langgraph_workflow.py` 覆盖旧输出文件、报告、论文可选路径和全局库函数跨任务复用。
- `test_api_results.py` 覆盖旧任务读取和缺失文件兼容。
- LLM/VLM/Teaching Diagram 测试使用 Mock Provider，覆盖授权、预算、缓存和 fallback。
- v1.3.5 基线为后端 218 passed、前端 29 passed，前端构建和 `scripts/validate.sh` 通过。

### 2.6 规则事实与模型解释

仓库扫描、AST、文件/函数/模型规则、论文文本与 Figure 本地提取、规则论文代码对齐属于事实或确定性候选。文件/函数/模型 LLM explanation、Figure VLM、论文对齐 LLM 建议和教学图 AI 内容属于解释层。v1.4.0 的实体和关系只能由前一类输入构建；模型结果不能覆盖、删除或伪造规则事实。

## 3. 本阶段目标

v1.4.0 只完成：

1. `CodeEntity`。
2. `PaperEntity`。
3. `KnowledgeEdge`。
4. `EvidenceRef`。
5. 稳定 Entity ID、Edge ID、Chunk ID、Evidence ID。
6. 仓库级 Symbol Table。
7. Import Resolver，覆盖 import、alias、from import 和 relative import。
8. Call Graph Builder，覆盖普通调用、方法、`self.method()` 和可确定的 `self.module(x) → forward`。
9. 保留 unresolved 和 ambiguous call。
10. Symbol-aware Chunk。
11. `indexed_files` 文件快照记录。
12. SQLite 版本化持久化。
13. `index_manifest.json`。
14. 幂等、并发、失败重试、版本激活和旧 active 清理机制。

## 4. 非目标

本阶段明确不实现：

- Hybrid RAG、Dense/Sparse/Graph Retrieval 或 Reranker。
- 向量数据库或 embedding。
- 动态 Research Agent 或 Multi-Agent。
- Trace 前端、Evaluation Dashboard 或 Bad Case 系统。
- PostgreSQL、Redis、Celery、Neo4j 或分布式任务队列。
- LLM 自动修正调用图。
- Git rename/移动历史推断。
- 强制重写旧前端、旧报告或旧分析 JSON。
- 对动态 Python、反射、monkey patch、Registry/Factory 做不可靠的确定解析。

## 5. 目标数据模型

以下为拟议 Pydantic 边界，字段名和语义在 v1.4.0-a 冻结；实现时使用 `Field(default_factory=...)`，不得使用可变默认值。

### 5.1 CodeEntity

```python
class CodeEntity(BaseModel):
    id: str
    repo_id: str
    entity_type: Literal[
        "repository", "directory", "file", "class", "function", "method",
        "model_module", "config", "training_entry", "inference_entry", "dataset"
    ]
    path: str
    name: str
    qualified_name: str
    module_name: str | None = None
    parent_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None
    source_code: str | None = None
    docstring: str | None = None
    content_hash: str
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

关系：

- file/class/function/method 主要由 `ParsedFile`、`ClassInfo` 和 `FunctionInfo` 转换。
- file role 由 `FileAnalysis` 增量映射为 config/training/inference/dataset 等实体或 metadata。
- model module 由 `ModelAnalysis.layers` 和 `forward_steps` 构建。
- `source_code` 和行号保持规则解析事实；LLM summary 不写入本模型核心事实字段。

### 5.2 PaperEntity

```python
class PaperEntity(BaseModel):
    id: str
    paper_id: str
    entity_type: Literal[
        "section", "paragraph", "formula", "figure", "table", "contribution", "method_module"
    ]
    title: str | None = None
    text: str
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    figure_path: str | None = None
    keywords: list[str] = Field(default_factory=list)
    module_names: list[str] = Field(default_factory=list)
    content_hash: str
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

关系：

- Section/Contribution 复用 `PaperAnalysis`。
- Figure 复用 `PaperFigure` 的稳定 Figure ID、页码、bbox、caption 和资产路径。
- v1.4 不凭空补造当前规则解析未提供的公式或表格；没有事实时不创建对应实体。

### 5.3 KnowledgeEdge

```python
class KnowledgeEdge(BaseModel):
    id: str
    repo_id: str
    source_id: str
    target_id: str | None = None
    edge_type: Literal[
        "CONTAINS", "DEFINES", "IMPORTS", "CALLS", "INHERITS", "INSTANTIATES",
        "CONFIGURES", "TRAINS", "USED_IN_INFERENCE", "NEXT_MODULE", "ALIGNS_WITH"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    resolution_type: Literal[
        "exact", "alias", "relative", "self_method", "model_forward",
        "duplicate_last_definition", "ambiguous", "unresolved"
    ]
    unresolved_symbol: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

`target_id=None` 时必须有 `unresolved_symbol`，且 `resolution_type` 必须为 ambiguous 或 unresolved。相同逻辑关系聚合多个 evidence，避免仅因行号移动产生新 Edge ID。

### 5.4 EvidenceRef

```python
class EvidenceRef(BaseModel):
    id: str
    source_type: Literal["code", "paper", "figure", "alignment"]
    entity_id: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    paper_id: str | None = None
    page_number: int | None = None
    figure_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    content_hash: str | None = None
```

### 5.5 SymbolChunk

```python
class SymbolChunk(BaseModel):
    id: str
    repo_id: str
    entity_id: str
    entity_kind: Literal["code", "paper"]
    chunk_type: Literal["function", "method", "class", "file", "model_module", "paper_entity"]
    path: str | None = None
    page_number: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    ordinal: int = 0
    text: str
    content_hash: str
    char_count: int
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

Chunk 优先按函数、方法、类、文件、模型模块或论文实体切分，不引入 tokenizer 或固定字符盲切。超长实体可按 AST 子块生成多个 ordinal chunk，但每个 chunk 必须保留实体和范围。

### 5.6 IndexedFile

```python
class IndexedFile(BaseModel):
    path: str
    kind: Literal["python", "config", "other"]
    content_hash: str
    size_bytes: int = Field(ge=0)
    parse_status: Literal["success", "partial", "failed", "skipped"]
    entity_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    errors: list[dict[str, JsonValue]] = Field(default_factory=list)
```

### 5.7 IndexManifest

```python
class IndexManifest(BaseModel):
    manifest_version: str
    index_schema_version: str
    repo_id: str
    repository_identity_mode: Literal["explicit", "task_scoped"]
    index_version_id: str
    index_sequence: int
    input_hash: str
    status: Literal["active", "failed", "in_progress", "reused"]
    builder_versions: dict[str, str]
    file_count: int
    code_entity_count: int
    paper_entity_count: int
    edge_count: int
    evidence_count: int
    chunk_count: int
    unresolved_call_count: int
    ambiguous_call_count: int
    created_at: datetime
    activated_at: datetime | None = None
    warnings: list[dict[str, JsonValue]] = Field(default_factory=list)
```

## 6. 稳定 ID、路径、模块根与 input_hash

### 6.1 仓库身份

`repo_id` 有两种模式：

1. 显式 `repository_key`：执行 Unicode NFC、去除首尾空白、校验非空，然后：

   ```text
   SHA256("repo:v1\0explicit\0" + normalized_repository_key)
   ```

2. 未提供 `repository_key`：必须使用 task-scoped 身份：

   ```text
   SHA256("repo:v1\0task\0" + task_id)
   ```

未提供显式 key 时，禁止根据 ZIP 文件名、上传文件名、仓库目录名或内容 hash 跨任务合并。Task-scoped 模式只保证同一任务内重试稳定。

### 6.2 路径规范化

- 输入必须转换为仓库相对 POSIX 路径。
- `\` 转为 `/`，消除 `.`、重复分隔符和空组件。
- 拒绝绝对路径、Windows 盘符、UNC 路径及任何 `..` 逃逸。
- 每个路径组件执行 Unicode NFC，保留大小写，不 case-fold。
- 数据库存规范化路径；原始路径只允许进入诊断 metadata。
- Windows、macOS 和 Linux 表示同一逻辑路径时必须得到同一 ID。

### 6.3 模块根

模块根优先级：

1. 使用 Python 3.11 标准库 `tomllib` 读取 `pyproject.toml` 中明确配置的 package root。
2. 仓库 `src/`。
3. 仓库根。

同一文件匹配多个根时选择优先级最高且相对路径最长的有效根。经典包要求父目录链存在 `__init__.py`；显式 root 或 `src/` 下允许 namespace package。不能唯一确定时保留所有候选，标记 ambiguous，不静默选择低证据目标。

### 6.4 实体、关系和 Chunk ID

- directory/file：`repo_id + entity_type + normalized_path`。
- class/function/method：`repo_id + entity_type + normalized_path + full_qualified_name`。
- 重复声明：在上述 canonical key 后追加 `#decl:<source-order>`。
- model module：`parent_class_entity_id + normalized_member_name`。
- PaperEntity：`paper_id + entity_type + page_or_figure_id + stable_page_ordinal`。
- Edge：`source_id + edge_type + target_id`；unresolved 使用规范化调用表达式代替 target。
- Chunk：`entity_id + chunk_type + ordinal + content_hash`。
- Evidence：`source_type + source locator + content_hash`。

所有 ID 使用带类型前缀的 SHA-256，例如 `ent_<hex>`、`edge_<hex>`、`chunk_<hex>`。普通实体 ID 不包含行号或内容 hash，避免常规编辑和上方插入代码导致漂移。

文件移动视为旧实体删除和新实体创建。v1.4 不推断 rename。

### 6.5 重复符号

Symbol Table 的 key 始终映射到候选列表：

- 唯一符号不使用 declaration ordinal。
- 同一作用域重复定义按 AST source order 标记 `#decl:1`、`#decl:2`，并设置 `duplicate_symbol=true`。
- 无条件模块级重复定义可按 Python 后定义覆盖规则解析到最后声明，但必须保留全部候选和 evidence，使用 `duplicate_last_definition`。
- 位于 if/try/loop 等条件作用域的重复定义保持 ambiguous。
- 新增或删除同名声明会造成 ordinal 漂移，这是 v1.4 的已知限制，不能声称完全稳定。

### 6.6 内容哈希

- 代码文本：去除 UTF-8 BOM，将 CRLF/CR 规范化为 LF，其余字符、空白和最终换行保持不变，再做 SHA-256。
- PDF：对原始文件字节做 SHA-256。
- `content_hash` 与 entity ID 分离；内容修改更新 hash 和 index version，但不必改变具名实体 ID。

### 6.7 input_hash

`input_hash` 是以下 canonical JSON 的 SHA-256：

```json
{
  "input_hash_version": "1",
  "repo_id": "...",
  "repository_identity_mode": "explicit|task_scoped",
  "index_schema_version": "...",
  "path_normalization_version": "...",
  "parser_version": "...",
  "builder_versions": {
    "code_entity": "...",
    "paper_entity": "...",
    "symbol_table": "...",
    "import_resolver": "...",
    "call_graph": "...",
    "chunker": "..."
  },
  "effective_options": {
    "module_roots": ["..."],
    "indexed_extensions": ["..."],
    "ignored_directories": ["..."],
    "max_file_bytes": 0,
    "paper_max_pages": 0,
    "paper_max_text_chars": 0,
    "chunk_policy_version": "...",
    "unresolved_policy_version": "..."
  },
  "files": [
    {
      "path": "normalized/relative/path.py",
      "kind": "python|config|other",
      "size_bytes": 0,
      "content_hash": "..."
    }
  ],
  "paper": {
    "provided": false,
    "content_hash": null
  }
}
```

Canonicalization 规则：

- UTF-8；所有结构字符串执行 Unicode NFC。
- object key 字典序排列，紧凑分隔符，禁止 NaN/Infinity。
- `files` 按 path、kind 排序；module roots、扩展名和 ignore dirs 排序去重。
- 数值和布尔值使用 JSON 原生类型。
- 不包含时间、绝对路径、output dir、ZIP 文件名、Provider 配置、LLM/VLM 开关或模型结果。
- task ID 不单独进入 payload；task-scoped 模式已通过 repo ID 表达其身份。
- 任何会改变确定性文件选择、实体、关系或 Chunk 的 Schema、解析器、Builder 和有效配置都必须进入 payload。
- Schema/Builder 版本变化必须改变 input hash；顺序或 JSON 格式差异不得改变 hash。

## 7. 数据库设计

使用独立 `data/structured_index.sqlite3`，不得修改或复用现有 `python_function_library.sqlite3` 和 AI cache 数据库。

### 7.1 表与关键约束

#### repositories

- 主键：`repo_id TEXT`。
- 字段：identity mode、repository key、display name、active version ID、created/updated time。
- 显式 repository key 使用条件唯一索引；task-scoped row 不参与跨任务 key 唯一约束。

#### index_versions

- 主键：`index_version_id TEXT`。
- 外键：`repo_id → repositories.repo_id ON DELETE CASCADE`。
- 字段：sequence、input hash、状态、retry count、lease owner/expiry、error JSON、created/ready/activated/failed time。
- 唯一：`(repo_id, sequence)`、`(repo_id, input_hash)`。
- 每个 repo 最多一个 active 版本，并通过 partial unique index 约束。
- 每个 repo 最多一个持有有效构建 lease 的 building/ready 版本。

#### indexed_files

- 主键：`(index_version_id, path)`。
- 外键：index version，级联删除。
- 字段：kind、content hash、size、parse status、实体/边/chunk 数和错误 JSON。
- 索引：path、content hash、parse status。

#### code_entities / paper_entities

- 主键：`(index_version_id, entity_id)`。
- 外键：index version，级联删除。
- 索引：repo/type/path/qualified name/content hash；论文另索引 page/figure。
- code parent 关系在同一 index version 内验证。

#### knowledge_edges

- 主键：`(index_version_id, edge_id)`。
- 外键：index version，级联删除。
- 索引：source、target、edge type、resolution type。
- source/target 可指向代码或论文实体，SQLite 无法对两个目标表建立单一多态 FK，因此在激活事务前执行应用级完整性校验。

#### evidence_refs

- 主键：`(index_version_id, evidence_id)`。
- 外键：index version，级联删除。
- 索引：entity ID、file/path line、paper/page、figure ID。

#### symbol_chunks

- 主键：`(index_version_id, chunk_id)`。
- 外键：index version，级联删除。
- 字段：repo/entity、entity kind、chunk type、path/page/range、ordinal、text、content hash、char count、metadata JSON。
- 索引：entity ID、chunk type、path、content hash。
- 多态 entity 引用同样在激活前应用级验证。

### 7.2 版本状态机

```text
building → ready → active → superseded
building → failed
ready → failed
failed → building        # 有界重试
superseded → active      # 显式回滚时与当前 active 原子交换
```

- `active` 每个 repo 最多一个。
- building/ready 必须持有 repo lease；lease 过期视为 stale。
- stale 版本由下一请求在短事务中转 failed，再按 retry policy 决定是否回到 building。
- active 不允许直接 failed；激活失败时保留原 active，新版本进入 failed。

### 7.3 构建与事务边界

禁止在长时间 AST、符号解析、关系构建或 Chunk 构建期间持有 SQLite 写事务：

1. 短事务创建或取得 index version、获取 repo lease并设为 building。
2. 在写事务外读取文件、构建/验证实体关系和 Chunk；大型产物写任务目录临时 staging JSONL。
3. 短事务确认 lease 并将版本设为 ready。
4. 一个 `BEGIN IMMEDIATE` 短事务批量导入 staging，校验计数、引用和唯一约束，切换 active，并将旧 active 标记 superseded。
5. 提交后原子写最终 `index_manifest.json`。
6. 任一阶段失败时以短事务记录 failed；不得影响旧 active 或旧报告。

### 7.4 并发与重试

- 同 repo、同 input hash：有限等待后复用完成的 active 版本。
- 同 repo、不同 input hash：仅 lease 持有者构建；其他请求返回 retryable `index_busy`。
- 不同 repo 可以并行执行长时间构建；最终写入遵守 SQLite busy timeout。
- SQLite busy、临时锁和可判定的临时 IO 错误最多重试 3 次，采用集中配置的有界退避。
- 确定性解析、Schema 校验、引用完整性错误不自动重试。
- 失败重试复用相同 logical index version，增加 retry count；达到上限保持 failed。

### 7.5 删除与清理

每次索引构建完整新快照。新 active 中未出现的文件、实体、边和 Chunk 即从 active 视图消失。旧版本标记 superseded，默认不物理删除；显式 retention 操作才清理历史版本。不得在应用启动时无提示删除数据库或用户任务产物。

### 7.6 迁移

- 使用标准库 `sqlite3`、编号 SQL migration 和 `PRAGMA user_version`，不新增 Alembic 等依赖。
- 首个 migration 创建全部 v1.4 表、索引和约束。
- migration 在单独短事务中执行；失败回滚且 `user_version` 不前进。
- 每个 migration 提供适用版本、向前 SQL、验证查询和回滚说明。
- 结构化索引数据库与旧数据库完全分离，因此首次启用不会迁移或改变旧库数据。

## 8. 文件级修改清单

### 8.1 新增文件

| 文件 | 操作 | 作用 | 依赖 | 风险 |
| -- | -- | -- | -- | -- |
| `backend/app/domain/entities.py` | 新增 | CodeEntity、PaperEntity | Pydantic、旧规则 Schema | 字段过度耦合旧 JSON |
| `backend/app/domain/edges.py` | 新增 | KnowledgeEdge 和关系枚举 | entities | 多态引用完整性 |
| `backend/app/domain/evidence.py` | 新增 | EvidenceRef | entities/edges | evidence 去重与漂移 |
| `backend/app/domain/index_manifest.py` | 新增 | IndexedFile、SymbolChunk、IndexManifest | domain models | 版本字段遗漏导致幂等失真 |
| `backend/app/indexing/path_normalizer.py` | 新增 | 跨平台路径规范化和拒绝规则 | path utils | Windows/Unicode 边界 |
| `backend/app/indexing/module_roots.py` | 新增 | pyproject/src/root 模块根识别 | `tomllib` | namespace/多 root 歧义 |
| `backend/app/indexing/stable_ids.py` | 新增 | repo/entity/edge/evidence/chunk ID 与内容 hash | path normalizer | ID 漂移 |
| `backend/app/indexing/input_fingerprint.py` | 新增 | canonical payload 和 input hash | stable IDs/config | 漏掉影响索引的配置 |
| `backend/app/indexing/code_entity_builder.py` | 新增 | 从旧 AST/规则结果构建代码实体 | existing schemas | 重复符号处理 |
| `backend/app/indexing/paper_entity_builder.py` | 新增 | 从论文/Figure 规则事实构建论文实体 | paper schemas | 页码/序号稳定性 |
| `backend/app/indexing/symbol_table_builder.py` | 新增 | 仓库级候选符号表 | module roots/entities | 同名与条件定义 |
| `backend/app/indexing/import_resolver.py` | 新增 | import/alias/from/relative 解析 | symbol table | 循环/namespace import |
| `backend/app/indexing/call_graph_builder.py` | 新增 | CALLS/INSTANTIATES 等关系 | resolver/model facts | 动态调用误解析 |
| `backend/app/indexing/inheritance_resolver.py` | 新增 | INHERITS 关系 | resolver | 多继承和 alias |
| `backend/app/indexing/code_chunker.py` | 新增 | Symbol-aware Chunk | entities | 超长实体和重复内容 |
| `backend/app/indexing/index_service.py` | 新增 | 构建、staging、验证和持久化编排 | all indexing/persistence | 内存、失败隔离、并发 |
| `backend/app/persistence/migrations/001_structured_index.sql` | 新增 | 首版数据库 Schema | SQLite | migration/约束错误 |
| `backend/app/persistence/migration_runner.py` | 新增 | `PRAGMA user_version` 迁移 | sqlite3 | 半迁移 |
| `backend/app/persistence/index_store.py` | 新增 | version lease、批量写入、激活、回滚 | migration | 锁和事务边界 |
| `backend/app/agents/nodes/structured_index_build_node.py` | 新增 | 单一影子索引节点 | index service | 失败影响旧流程 |
| `tests/indexing/*` | 新增 | v1.4 单元、并发和集成测试 | fixtures | 覆盖不足 |
| `tests/fixtures/indexing_repo/*` | 新增 | alias、relative、duplicate、model、dynamic fixtures | tests | fixture 不代表真实边界 |

### 8.2 修改文件

| 文件 | 操作 | 作用 | 依赖 | 风险 |
| -- | -- | -- | -- | -- |
| `backend/app/schemas/state.py` | 修改 | 只增加 identity、DB path、version 和 manifest 摘要字段 | domain manifest | State 继续膨胀 |
| `backend/app/agents/graph.py` | 修改 | 在 `paper_code_align` 后插入一个结构化索引节点 | new node | 节点计数与进度测试变化 |
| `backend/app/services/analysis_options.py` | 修改 | 解析 feature flag、repository key 和 index DB path | existing options | Secret/runtime 错入 State |
| `backend/app/services/analysis_service.py` | 修改 | 传入索引选项，读取可选 `index_manifest.json` | new node/manifest | 旧任务缺失文件兼容 |
| `tests/test_langgraph_workflow.py` | 修改 | 验证节点位置、旧输出和影子失败隔离 | integration | 旧断言变脆弱 |
| `docs/architecture.md`、`docs/database.md`、`docs/agent_workflow.md` | 修改 | 版本完成后同步结构、迁移和流程 | implementation | 文档与实现漂移 |

### 8.3 不应修改的文件

| 文件/目录 | 操作 | 作用 | 依赖 | 风险 |
| -- | -- | -- | -- | -- |
| `frontend/` | 不修改 | v1.4 不要求新 UI | 旧 API | 强制前端重写 |
| `backend/app/tools/report_tool.py` | 不修改 | 保持旧报告生成语义 | 旧 JSON | 报告回退 |
| `backend/app/schemas/code.py` 现有字段 | 不删除/改义 | 保持旧 AST Schema | 旧分析节点 | 旧任务和测试破坏 |
| 现有分析 Node | 不重构 | 新索引旁路消费现有事实 | graph | 范围膨胀 |
| 现有 SQLite DB | 不迁移/改表 | 保持知识库和缓存兼容 | current services | 数据破坏 |

## 9. 分阶段实施顺序

### v1.4.0-a：领域模型与稳定 ID

- 输入：现有 Schema、路径工具、任务 ID、可选 repository key。
- 输出：领域模型、路径规范化、module root 发现、内容 hash、稳定 ID、input hash。
- 修改文件：新增 domain 和基础 indexing 模块；不接入 Graph。
- 测试：Entity/Edge/Chunk/Evidence ID、task-scoped/explicit repo ID、CRLF、BOM、Unicode、Windows/UNC、文件移动、Schema/Builder 版本变化。
- 验收条件：canonical 输入可重建相同 ID/input hash；非法路径拒绝；无显式 key 时不同 task 不合并。
- 回滚点：删除新增 domain/indexing 基础模块和专项测试，不影响旧流程。

### v1.4.0-b：Symbol Table 与 Import Resolver

- 输入：ParsedFile、CodeEntity、module roots。
- 输出：候选符号表、module map、resolved/ambiguous/unresolved import 结果。
- 修改文件：新增 symbol table、module roots 和 import resolver；必要时只增加内部 dataclass。
- 测试：import alias、from import、relative import、src layout、namespace package、循环导入、同名模块、重复符号、条件定义。
- 验收条件：所有 import 都有 exact/ambiguous/unresolved 结果；不能解析的事实不丢失。
- 回滚点：移除 resolver 层，领域模型和 ID 保留可独立使用。

### v1.4.0-c：Call Graph 与关系构建

- 输入：函数源码、raw call expressions、Symbol Table、Import Resolver、ModelAnalysis、规则论文对齐。
- 输出：CONTAINS、DEFINES、IMPORTS、CALLS、INHERITS、INSTANTIATES、NEXT_MODULE、ALIGNS_WITH 等边和 EvidenceRef。
- 修改文件：新增 call graph、inheritance resolver 和关系聚合器。
- 测试：local call、alias call、from import、`self.method()`、`self.module(x)`、实例化、重复定义、dynamic/Registry/Factory、unresolved 聚合。
- 验收条件：可确定调用精确解析；不确定调用保留 target null、调用文本和 evidence；相同行为多处调用聚合证据。
- 回滚点：移除关系 Builder，实体/Symbol Table 仍可工作。

### v1.4.0-d：Chunk、持久化与 Index Manifest

- 输入：所有领域对象、文件快照和 input hash。
- 输出：SymbolChunk、IndexedFile、SQLite active snapshot、`index_manifest.json`。
- 修改文件：新增 chunker、migration、store、index service 和 staging 逻辑。
- 测试：幂等、内容修改、文件删除、staging、短事务、rollback、lease、busy retry、stale build、并发和 migration。
- 验收条件：长构建不持有 SQLite 写锁；激活原子；失败保留旧 active；新 active 不含删除文件；manifest 与数据库计数一致。
- 回滚点：关闭持久化 feature flag，删除独立结构化索引 DB；旧输出不受影响。

### v1.4.0-e：集成、兼容、测试和文档

- 输入：完成的 IndexService 和旧规则状态。
- 输出：位于 `paper_code_align` 后的 `structured_index_build` 节点、可选任务 manifest、完整兼容记录。
- 修改文件：Graph、State、analysis options/service、相关测试和文档。
- 测试：节点位置、顺序 fallback、索引禁用/成功/失败、旧任务无 manifest、旧 JSON/报告/API/前端回归、完整验收。
- 验收条件：feature flag 关闭时行为等同 v1.3.5；开启后新增 manifest/DB，不改变旧 Schema 和规范化语义；完整 validate 通过。
- 回滚点：从 Graph 移除单一节点并关闭 flag；新模块和 DB 可保留但不被旧流程调用。

## 10. 兼容方案

### 10.1 旧输出

- `parsed_files.json` 必须继续保留，仍由旧 `report_generate_node` 生成。
- `file_analysis.json`、`function_analysis.json` 和 `model_analysis.json` 继续由旧规则节点生成和消费。
- 新实体从这些既有事实增量生成，不反向覆盖它们。
- `index_manifest.json` 是新增可选文件；读取旧任务时缺失该文件不产生致命错误。

### 10.2 报告和前端

- 旧 `report_tool` 和报告章节不改为依赖 SQLite。
- 现有 API 路由保持不变；任务结果可以增量包含可选 manifest，但旧字段不删除、不改义。
- `frontend/src/types/analysis.ts` 本阶段不要求修改，前端可忽略额外响应字段。
- 正常模式、零基础模式、库函数弹窗、模型、论文、Figure、Mermaid 和教学图继续使用旧结果。

### 10.3 兼容判定

兼容标准是 Schema 与规范化语义兼容，而不是字节结构兼容：

- 旧文件存在。
- 既有 top-level key、字段类型、含义和默认/缺失处理不变。
- 对结果执行规范化 JSON/Pydantic 比较时，核心事实等价。
- 不要求键顺序、缩进、空白、JSON 字节、无语义数组物理编码完全相同。

### 10.4 Feature flag

需要 feature flag。v1.4.0-a 至 d 默认不接入旧流程；v1.4.0-e 接入后先默认关闭。只有专项测试、旧流程回归和完整 validate 全部通过，才允许版本发布时默认开启。索引节点失败必须追加结构化错误/manifest 状态并继续旧报告流程。

## 11. 测试计划

建议新增目录 `tests/indexing/` 和 fixture `tests/fixtures/indexing_repo/`。

| 场景 | 建议测试文件 | Fixture/验证 |
| -- | -- | -- |
| Entity ID 稳定性 | `test_stable_ids.py` | 相同行为重复构建、上方插入行、内容修改 |
| Edge ID 稳定性 | `test_stable_ids.py` | 调用行移动、相同关系多 evidence |
| repo identity | `test_stable_ids.py` | explicit key 跨任务复用；无 key 时 task-scoped 隔离 |
| input hash | `test_stable_ids.py` | 文件排序、option 排序、Schema/Builder version、paper hash |
| 跨平台路径 | `test_path_and_module_roots.py` | `/`、`\`、盘符、UNC、Unicode NFC、大小写 |
| 模块根 | `test_path_and_module_roots.py` | pyproject root、src layout、repo root、namespace、多候选 |
| 重复符号 | `test_symbol_table.py` | 无条件重复、条件定义、同名类/函数、ordinal 漂移 |
| import alias | `test_import_resolver.py` | `import module as m` |
| from import | `test_import_resolver.py` | `from package.module import symbol as alias` |
| relative import | `test_import_resolver.py` | `.module`、`..package`、越界相对导入 |
| 循环导入 | `test_import_resolver.py` | 两包互相导入，不递归死循环 |
| local function call | `test_call_graph_builder.py` | 同模块和跨模块函数 |
| `self.method()` | `test_call_graph_builder.py` | 类内方法 exact 解析 |
| `self.module(x)` | `test_call_graph_builder.py` | `__init__` 实例绑定到 module `forward` |
| unresolved call | `test_call_graph_builder.py` | 参数 callable、getattr、Registry、动态 import |
| Symbol Chunk | `test_chunks.py` | 函数/类/文件/模型、超长实体 ordinal、hash |
| indexed_files | `test_index_persistence.py` | success/partial/failed/skipped 和计数 |
| 重复索引幂等 | `test_index_persistence.py` | 同 input hash 复用 active version |
| 文件修改 | `test_index_persistence.py` | 新 sequence、稳定实体 ID、更新 content hash |
| 删除文件 | `test_index_persistence.py` | 新 active 无旧实体，旧 superseded 可回查 |
| 事务回滚 | `test_index_persistence.py` | 导入/验证/激活中注入失败，旧 active 不变 |
| 长构建事务 | `test_index_concurrency.py` | Builder 阻塞期间另一连接可写无关 repo |
| 同 repo 并发 | `test_index_concurrency.py` | 同 hash 复用、不同 hash 得到 `index_busy` |
| 不同 repo 并发 | `test_index_concurrency.py` | 长构建并行、短写事务串行完成 |
| busy retry | `test_index_concurrency.py` | 锁冲突、3 次退避、retryable error |
| 失败重试 | `test_index_persistence.py` | failed→building、有界 retry、非重试错误 |
| stale lease | `test_index_concurrency.py` | 模拟进程崩溃后接管 |
| migration | `test_index_persistence.py` | 新库、重复迁移、失败 rollback、user_version |
| Schema 版本变化 | `test_stable_ids.py` | input hash/新 index version 变化，实体 ID 规则保持 |
| 旧流程回归 | `test_index_integration.py`、现有 workflow/API tests | flag off/on/failure、旧 JSON、报告和旧任务 |

每阶段至少覆盖正常、空输入、非法输入、部分失败、幂等和序列化/反序列化。自动测试不得访问真实 Provider。

最终必须运行并记录：

```bash
python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
bash scripts/validate.sh
```

## 12. 风险

### 12.1 符号与调用解析

- Python 动态调用、`getattr`、闭包、decorator 替换和 monkey patch 无法静态完整解析。
- Registry/Factory 可能隐藏真实实例类型；默认保留 unresolved/候选，不以低证据 exact edge 代替。
- 循环导入可能导致递归或不完整候选；Resolver 必须使用显式访问状态和候选集合。
- 同名符号和条件定义会产生 ambiguous；无条件重复定义虽可按后定义覆盖处理，也必须保留候选。
- `self.module(x)` 只有在 `__init__` 赋值和类定义可确定时才能映射到 `forward`。

### 12.2 路径与身份

- 相对导入依赖正确 module root；src layout、namespace package 和多根项目可能歧义。
- Windows 盘符、UNC、反斜杠、Unicode normalization 和大小写敏感性可能导致跨平台 ID 漂移。
- 文件移动会改变 entity ID；v1.4 不做 rename tracking。
- 重复符号 ordinal 在新增/删除同名声明后可能漂移。
- task-scoped identity 不跨任务复用，这是有意设计；需要跨任务版本时调用方必须提供 repository key。

### 12.3 数据库、并发与迁移

- SQLite 单 writer 会限制最终激活并发；必须把长构建移出写事务并缩短 `BEGIN IMMEDIATE`。
- 进程崩溃可能遗留 lease 和 staging；需要 stale recovery 和安全清理。
- busy retry 过度可能放大延迟，过少则导致瞬时失败；参数必须集中、有限且可测试。
- migration 错误可能使新索引不可用；独立数据库和事务迁移确保旧流程不受影响。
- 多态 entity FK 无法完全由 SQLite 表达，应用级验证遗漏会留下悬空关系。

### 12.4 性能与兼容

- 巨大仓库可能产生高 AST、内存和 staging IO 压力；需要流式/JSONL staging、批量插入和计数限制。
- 保存 source 和 chunk text 会增加数据库体积；必须有明确 retention，不能默认删除用户历史。
- Schema/Builder 版本遗漏会错误复用旧 input hash。
- 新节点若错误传播会阻断报告；必须隔离失败并保留旧流程。
- 旧输出兼容应按 Schema 与规范化语义验证，避免把非语义 JSON 编码差异误判为回退，也避免只检查文件存在而漏掉字段含义变化。

## 13. Definition of Done

v1.4.0 只有同时满足以下条件才完成：

1. `CodeEntity`、`PaperEntity`、`KnowledgeEdge`、`EvidenceRef`、`SymbolChunk`、`IndexedFile` 和 `IndexManifest` 均有版本化 Pydantic Schema。
2. explicit 和 task-scoped repo identity 按本计划实现；无 key 时绝不按 ZIP 文件名跨任务合并。
3. 路径规范化、模块根、内容 hash、Entity/Edge/Chunk/Evidence ID 和完整 input hash 均有固定版本与自动测试。
4. Symbol Table 保留重复候选；Import Resolver 覆盖 alias、from import、relative import、namespace 和循环导入。
5. Call Graph 覆盖 local call、`self.method()`、可确定的 `self.module(x)`；unresolved 和 ambiguous 不丢失。
6. 所有实体和关系都有代码路径/行号或论文页码/Figure/bbox 证据。
7. SQLite 包含 repositories、index_versions、indexed_files、code/paper entities、edges、evidence 和 symbol_chunks，并有编号 migration。
8. 长时间构建不持有 SQLite 写事务；最终激活原子，失败保留旧 active。
9. 版本状态机、lease、stale recovery、同/不同 repo 并发、busy retry 和失败重试都有自动测试。
10. 同 input hash 重复索引复用版本；修改产生新版本；删除文件后新 active 不包含旧实体；旧 superseded 可显式回滚。
11. `index_manifest.json` 与 active 数据库版本和统计一致。
12. 新索引只消费规则事实，不使用 LLM/VLM 解释修改事实图。
13. `structured_index_build` 位于 `paper_code_align` 之后、所有 LLM/VLM 增强之前，旧节点相对顺序不变。
14. 旧 `parsed_files.json`、`file_analysis.json`、`function_analysis.json`、报告、API 和前端达到 Schema 与规范化语义兼容。
15. feature flag 关闭时行为与 v1.3.5 等价；索引失败不阻断旧报告。
16. 新代码没有第三方依赖、没有真实 Provider 自动调用、没有前端强制改造。
17. 后端全量测试、前端测试、前端构建和 `scripts/validate.sh` 全部通过，并记录真实结果和已知限制。

