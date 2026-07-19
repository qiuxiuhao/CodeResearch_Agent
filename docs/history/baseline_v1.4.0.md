# CodeResearch Agent v1.4.0 验收基线

记录日期：2026-07-17  
工作分支：`upgrade/v1.4-structured-index`

## 1. Git 与运行环境

本次检查在 Conda 环境 `code-research-agent` 中完成。

| 项目 | 实际值 |
| -- | -- |
| Git commit | `04ea17e v1.4:结构化索引基础开发` |
| 当前分支 | `upgrade/v1.4-structured-index` |
| 审计前工作区 | `git status --short` 无输出，工作区干净 |
| Python | 3.11.15 |
| Node.js | v24.15.0 |
| Python/后端项目版本 | 1.4.0 |
| 前端包版本 | 1.3.5 |
| Python SQLite | 3.53.3，编译选项包含 `ENABLE_FTS5` |

完整验收和临时索引检查后再次执行 `git status --short`，仍无输出。本轮未创建 Git commit。

## 2. 完整验收结果

### 2.1 后端

命令：

```bash
python -m pytest -q
```

结果：通过。

```text
245 passed, 6 warnings in 52.97s
```

### 2.2 前端测试

命令：

```bash
npm --prefix frontend test
```

结果：通过。

```text
Test Files  16 passed (16)
Tests       29 passed (29)
Duration    1.38s
```

### 2.3 前端构建

命令：

```bash
npm --prefix frontend run build
```

结果：通过。TypeScript typecheck、Vite production build 和 build contract 均通过。Vite 仍提示部分 chunk 大于 500 kB，该提示未导致失败。

### 2.4 完整验收脚本

命令：

```bash
bash scripts/validate.sh
```

结果：通过。脚本内再次得到：

- 后端 245 passed、6 warnings，52.83s。
- 前端 16 个测试文件、29 个测试通过。
- 前端 typecheck、production build 和 build contract 通过。
- `npm ci` 成功，提示 `whatwg-encoding@3.1.1` 已弃用。

## 3. 已知警告和失败

本轮没有测试、构建或验收失败。实际观察到：

1. PyMuPDF/SWIG 类型触发缺少 `__module__` 的 `DeprecationWarning`。
2. Starlette `TestClient` 触发 httpx 调用方式弃用警告。
3. npm 提示 `whatwg-encoding@3.1.1` 已弃用。
4. Vite 提示部分生产 chunk 超过 500 kB。

这些均为既有警告，本轮未修改代码处理。

## 4. v1.4 领域模型实际字段

### 4.1 `CodeEntity`

定义：`backend/app/domain/entities.py`

| 字段 | 类型/约束 | 含义 |
| -- | -- | -- |
| `id` | `str` | 稳定代码实体 ID |
| `repo_id` | `str` | 仓库身份 |
| `entity_type` | Literal | repository、directory、file、class、function、method、model_module、config、training_entry、inference_entry、dataset |
| `path` | `str` | 规范化仓库相对 POSIX 路径 |
| `name` | `str` | 局部名称 |
| `qualified_name` | `str` | 完整限定名 |
| `module_name` | `str \| None` | Python 模块名 |
| `parent_id` | `str \| None` | 父实体 ID |
| `start_line` / `end_line` | `int \| None` | 源码范围 |
| `signature` | `str \| None` | 函数或方法签名 |
| `source_code` | `str \| None` | 规则解析得到的源码 |
| `docstring` | `str \| None` | Docstring |
| `content_hash` | `str` | 与实体身份分离的内容哈希 |
| `evidence_refs` | `list[str]` | 证据 ID |
| `metadata` | JSON 字典 | 扩展事实和诊断数据 |

### 4.2 `PaperEntity`

定义：`backend/app/domain/entities.py`

实际字段为 `id`、`paper_id`、`entity_type`、`title`、`text`、`page_number`、`bbox`、`figure_path`、`keywords`、`module_names`、`content_hash`、`evidence_refs`、`metadata`。实体类型包括 section、paragraph、formula、figure、table、contribution 和 method_module；构建器只对现有规则论文事实创建实体，不补造缺失类型。

### 4.3 `KnowledgeEdge`

定义：`backend/app/domain/edges.py`

实际字段为 `id`、`repo_id`、`source_id`、`target_id`、`edge_type`、`confidence`、`resolution_type`、`unresolved_symbol`、`evidence_refs` 和 `metadata`。`target_id=None` 时必须使用 unresolved 或 ambiguous 解析类型，并保存 `unresolved_symbol`；因此未解析调用没有被静默丢弃。

### 4.4 `EvidenceRef`

定义：`backend/app/domain/evidence.py`

实际字段为 `id`、`source_type`、`entity_id`、`file_path`、`start_line`、`end_line`、`paper_id`、`page_number`、`figure_id`、`bbox` 和 `content_hash`，可以表达代码路径/行号以及论文页码/Figure/bbox 证据。

### 4.5 `SymbolChunk`、`IndexedFile` 与 `IndexManifest`

定义：`backend/app/domain/index_manifest.py`

- `SymbolChunk`：`id`、`repo_id`、`entity_id`、`entity_kind`、`chunk_type`、`path`、`page_number`、`start_line`、`end_line`、`ordinal`、`text`、`content_hash`、`char_count`、`metadata`。
- `IndexedFile`：规范化路径、文件类型、内容哈希、字节数、解析状态、实体/关系/Chunk 数量和错误摘要。
- `IndexManifest`：Manifest/Schema 版本、repository identity mode、repo/index version、sequence、input hash、状态、builder versions、实体/边/证据/Chunk/文件和 unresolved/ambiguous 统计、时间及 warnings。

## 5. 身份、哈希与版本实现

### 5.1 Repository identity

定义：`backend/app/indexing/stable_ids.py`

- 显式 `repository_key` 经 Unicode NFC、去除首尾空白并校验非空后，参与 `repo:v1\0explicit\0...` 的 SHA-256。
- 未提供 key 时使用 `repo:v1\0task\0{task_id}`，只在任务内稳定。
- ZIP 文件名、上传名和解压目录不会用于跨任务合并。
- 实际 repo ID 带 `repo_` 前缀；Manifest 记录 `explicit` 或 `task_scoped`。

### 5.2 Entity、Edge、Chunk 与内容哈希

- 文件/目录 ID 由 repo、类型和规范化路径产生。
- class/function/method ID 还包含完整限定名；同作用域重复声明增加 declaration ordinal。
- model module ID 由父 class entity 和规范化成员名产生。
- PaperEntity ID 由 paper ID、类型、稳定 locator 和 ordinal 产生。
- Edge ID 由 source、edge type、target 产生；未解析边用规范化调用表达式替代 target。调用行号不参与 Edge ID，多条证据可聚合到同一逻辑边。
- Chunk ID 由 entity、chunk type、ordinal 和内容哈希产生。因此实体身份可保持稳定，而 Chunk 会随可检索文本变化。
- 代码文本哈希去除 UTF-8 BOM，将 CRLF/CR 规范化为 LF，其余字符和最终换行保持不变；PDF 使用原始字节 SHA-256。

### 5.3 `input_hash`

定义：`backend/app/indexing/input_fingerprint.py`

实际 payload 包含 repo identity、index/path/parser/builder 版本、影响确定性构建的 effective options、排序后的文件路径/类型/大小/content hash 和可选论文 content hash。对象 key、文件和集合值执行稳定排序与 JSON canonicalization；时间、绝对输出目录、ZIP 文件名、Provider/LLM/VLM 配置和模型解释不参与哈希。

## 6. 路径、模块根和符号解析

- `path_normalizer.py` 将路径规范化为仓库相对 POSIX 路径，拒绝绝对路径、Windows 盘符、UNC 和 `..` 逃逸，组件执行 Unicode NFC 并保留大小写。
- `module_roots.py` 按显式 package root、`src/`、仓库根识别模块根；无法唯一判断时保留歧义，而不是静默猜测。
- `symbol_table_builder.py` 将同一 key 映射为候选列表。普通唯一符号不使用行号或内容哈希；无条件重复定义可按后定义覆盖并保留全部候选，条件/动态重复定义保留 ambiguous/unresolved。
- `import_resolver.py` 覆盖 import alias、from import 和 relative import。
- `call_graph_builder.py` 覆盖局部函数、`self.method()`、可确定的 `self.module(x) -> forward`、实例化和 unresolved call。
- 动态调用、反射、Registry/Factory、运行时 import 和不能证明的多候选不会被强行解析。

## 7. SQLite Schema 与查询能力

### 7.1 实际数据库

- 默认路径：`data/structured_index.sqlite3`。
- migration runner：`backend/app/persistence/migration_runner.py`。
- 当前 migration：`backend/app/persistence/migrations/001_structured_index.sql`。
- 实际 `PRAGMA user_version=1`。

实际表共 8 张：

1. `repositories`
2. `index_versions`
3. `indexed_files`
4. `code_entities`
5. `paper_entities`
6. `knowledge_edges`
7. `evidence_refs`
8. `symbol_chunks`

数据库为 path、qualified name、content hash、实体/边/Chunk 类型、source/target、resolution type 和 parse status 建立索引。版本化表使用 `index_version_id` 隔离；repository/index version 外键和级联规则由 migration 固定。

### 7.2 Active version

`repositories.active_version_id` 外键指向 `index_versions.index_version_id`；每个 repo 最多一个 active version。`StructuredIndexStore` 当前提供版本创建、ready、激活、失败、显式回滚、计数和解析统计，但没有面向 v1.5 的公共只读接口来：

- 按 `repo_id` 获取 active version；
- 分页查询 Entity/Chunk/Evidence；
- 按 source、target、edge type 查询关系或邻居。

v1.5 必须先增加只读 Repository/Store 边界，不能让检索层直接散落 SQL。

### 7.3 状态机与事务

实际持久化流程使用 `building -> ready -> active -> superseded`、失败状态、lease、stale lease 恢复、有限重试和显式版本回滚。长时间文件读取、AST/符号/关系/Chunk 构建及 staging 在 SQLite 写事务之外完成；最终以短 `BEGIN IMMEDIATE` 事务批量激活。激活失败保留旧 active version。

同 repo 同 input 可复用已完成版本；同 repo 不同 input 受 lease 串行化；不同 repo 可并发构建并在 SQLite busy 时有限退避。superseded 历史默认保留，未实现自动 retention API。

## 8. 工作流与 Feature Flag

实际顺序为：

```text
paper_figure_extract
-> paper_code_align
-> structured_index_build
-> file_explain_llm
-> function_explain_llm
-> model_explain_llm
-> paper_figure_analyze_vlm
-> paper_code_align_llm
```

因此索引可使用规则论文代码对齐，但不消费后续 LLM/VLM 解释。

- `STRUCTURED_INDEX_ENABLED` 默认 `false`。
- API/CLI 可显式传入 `structured_index_enabled`、`repository_key` 和 DB path。
- 关闭时不创建索引数据库、不写 `index_manifest.json`，`index_manifest` 状态为空。
- 构建节点捕获错误并将结构化错误加入状态；索引失败不阻断旧报告流程。
- `analysis_service.TASK_RESULT_FILES` 已能读取可选 `index_manifest.json`，但当前没有索引查询或检索 API。

## 9. 真实索引样本检查

本轮在 `/private/tmp` 隔离目录中对 `examples/small_pytorch_project.zip` 执行一次显式仓库身份、无论文的结构化索引。该检查没有写入项目数据库或工作区。

### 9.1 Manifest 摘要

```json
{
  "manifest_version": "1.4.0",
  "index_schema_version": "1.4.0",
  "repository_identity_mode": "explicit",
  "repo_id": "repo_1d0ec11...274d8c",
  "index_version_id": "idx_cbe67f...a256e9",
  "index_sequence": 1,
  "input_hash": "8f0c7b...a56b3e",
  "status": "active",
  "file_count": 6,
  "code_entity_count": 19,
  "paper_entity_count": 0,
  "edge_count": 36,
  "evidence_count": 38,
  "chunk_count": 16,
  "unresolved_call_count": 11,
  "ambiguous_call_count": 0,
  "warnings": []
}
```

### 9.2 Entity、Edge 与 Chunk 统计

CodeEntity：class 2、config 1、dataset 1、directory 2、file 3、function 2、method 4、model_module 2、repository 1、training_entry 1，共 19。无论文输入，因此 PaperEntity 为 0。

Edge：

| edge type / resolution | 数量 |
| -- | --: |
| `CALLS / alias` | 1 |
| `CALLS / self_method` | 2 |
| `CALLS / unresolved` | 7 |
| `CONTAINS / exact` | 10 |
| `DEFINES / exact` | 8 |
| `IMPORTS / exact` | 2 |
| `IMPORTS / relative` | 1 |
| `IMPORTS / unresolved` | 3 |
| `INHERITS / unresolved` | 1 |
| `INSTANTIATES / alias` | 1 |

未解析样本包括 `super().__init__`、`nn.Linear`、`super`、`F.relu`、`torch.randn`、`model` 和 `output.mean`；记录均保留空 target、unresolved symbol 和源码证据。

Chunk：class 2、file 6、function 2、method 4、model_module 2，共 16。代码 Chunk 文本来自实体 `source_code`，缺失时回退为 qualified name/signature/docstring；论文 Chunk 使用论文实体文本。样本 Chunk 长度约 32 至 387 字符，`metadata` 当前为空对象。

检索层不能假定 Chunk payload 已直接包含 `entity_type` 或 `qualified_name`；同步到检索存储时必须按 `entity_id` 连接实体表补全过滤 metadata。file/class/function 层级可能含重叠源码，Context Builder 必须做父子去重。

## 10. v1.4 新增测试覆盖

`tests/indexing/` 现有 6 个测试文件、27 项测试：

- `test_domain_models.py`：模型 round-trip、targetless edge 校验。
- `test_stable_ids.py`：repository/entity/edge/chunk ID、文本哈希、input hash。
- `test_path_and_module_roots.py`：跨平台路径、Unicode、安全拒绝和模块根。
- `test_symbol_resolution.py`：重复符号、alias/from/relative import、循环导入、继承、局部/self/model 调用和 unresolved。
- `test_index_persistence.py`：migration、版本状态机、幂等、长构建无写锁、并发、lease、重试、事务/迁移失败回滚。
- `test_index_integration.py`：节点位置、feature flag、task-scoped 隔离、旧输出兼容、修改/删除文件后的新快照。

## 11. 可直接供 v1.5 复用的能力

1. `SymbolChunk` 是 Dense/Sparse 的最小文本输入，`content_hash` 可用于增量向量同步。
2. Code/Paper Entity 提供过滤、展示、父子关系和证据元数据。
3. `KnowledgeEdge` 提供 Graph Expansion 的事实图，source/target/type 已建立 SQL 索引。
4. `EvidenceRef` 可直接生成路径、行号、论文页码和 Figure 引用。
5. stable IDs、repo identity 和 index version 可作为检索缓存、Qdrant payload 和评测 gold key。
6. active/superseded 快照和 input hash 可用于检索索引幂等、失效、重建和删除。
7. `StructuredIndexStore` 的连接、migration、短事务和 retry 模式可复用；检索读取仍需新增专用只读接口。
8. `docs/evaluation_baseline_v1.3.5.md` 的固定 30 问可作为 v1.5 Benchmark 的问题种子，但目前没有 gold entity/chunk ID 和检索指标。

## 12. 已知问题与 v1.5 兼容要求

### 已知问题

- 动态 Python、Registry/Factory、反射、运行时 import 和部分外部库调用仍为 unresolved。
- `SymbolChunk.metadata` 尚未携带完整过滤字段，检索同步需要连接实体。
- Store 尚无 active snapshot、Chunk 搜索和 Graph neighbor 公共读接口。
- 大仓库构建仍为单进程内存对象加 staging，未分片并行。
- superseded 版本无自动 retention；向量层必须避免先删事实再删向量造成悬空。
- 当前没有真实论文样本的本轮索引统计，也没有任何 Dense/Sparse/Reranker 模型验收。

### v1.5 必须保持

1. `repo_id + index_version_id` 是所有检索和向量查询的强制隔离条件。
2. 只读取 active 或调用方明确指定且可读的版本，不能跨版本混合候选。
3. v1.4 Entity/Edge/Chunk/Evidence ID 和语义保持稳定；模型变化不能改写事实 ID。
4. unresolved/ambiguous edge 必须保留为证据，但不能作为有 target 的图边遍历。
5. SQLite 继续作为结构化事实源，向量索引是可重建派生缓存。
6. 旧 `parsed_files.json`、`file_analysis.json`、`function_analysis.json`、报告、API 和前端保持 Schema 与规范化语义兼容。
7. 检索和模型失败不得破坏旧 active index 或旧分析报告。
8. 自动测试、默认启动和离线模式不得下载真实 Embedding/Reranker 模型。

本基线只记录实际检查事实，没有实现任何 v1.5 检索功能。
