# 数据库说明

CodeResearch Agent 使用 SQLite 存储全局 Python 函数教学知识库。

这个知识库只记录库函数本身的教学级解释，例如一句话作用、通俗解释、常见参数、返回值、代码例子、shape 注意事项和常见误区。它不记录库函数在每个项目、文件、函数或行号中的出现位置。

## 默认路径

```text
data/python_function_library.sqlite3
```

可以通过以下方式覆盖：

- `LIBRARY_DB_PATH`
- `run_analysis(..., library_db_path=...)`
- API 请求字段 `library_db_path`

## 数据表

### `library_functions`

每个标准库函数保存一条教学级说明。

主要字段：

- `canonical_name`
- `display_name`
- `package_name`
- `category`
- `summary`
- `beginner_explanation`
- `parameters_explanation`
- `return_explanation`
- `common_usage`
- `code_example`
- `shape_or_tensor_note`
- `common_mistakes`
- `related_functions`
- `confidence`
- `created_at`
- `updated_at`

## Git 提交规则

本地 SQLite 文件属于运行时数据，不应提交：

```text
data/*.sqlite3
data/*.sqlite3-*
data/*.db
```

数据库 schema 会在服务首次使用时自动创建。

## v1.4 结构化索引数据库

结构化索引与全局函数库、LLM/Vision/Image 缓存完全分离，默认路径为：

```text
data/structured_index.sqlite3
```

可通过 `STRUCTURED_INDEX_DB_PATH`、`run_analysis(..., structured_index_db_path=...)`、CLI 或 API 字段覆盖。索引默认关闭，开启后才会使用该数据库。

### Migration

`backend/app/persistence/migrations/001_structured_index.sql` 是编号向前迁移，当前 `PRAGMA user_version=1`。迁移使用标准库 `sqlite3`，失败时回滚，不会删除重建现有数据库；数据库版本高于当前代码支持版本时拒绝启动索引。

### 表与约束

- `repositories`：`repo_id` 主键，显式 `repository_key` 条件唯一，记录当前 active version。
- `index_versions`：版本主键，`(repo_id, sequence)` 与 `(repo_id, input_hash)` 唯一；每个 repo 最多一个 active 和一个 building/ready。
- `indexed_files`：以 `(index_version_id, path)` 为主键，保存规范化路径、内容哈希、解析状态和实体/边/Chunk 数量。
- `code_entities`、`paper_entities`：版本化实体快照。
- `knowledge_edges`：版本化关系，包含 resolution type 和 unresolved symbol。
- `evidence_refs`：代码行、论文页/Figure/bbox 或对齐证据。
- `symbol_chunks`：以实体为边界的版本化文本 Chunk。

版本及其子表通过外键级联删除；多态实体引用由激活前完整性校验保证。常用 path、qualified name、实体/边/Chunk 类型、source/target、resolution、hash 和 parse status 均有索引。

### 事务和状态机

```text
building → ready → active → superseded
building → failed
ready → failed
failed → building
superseded → active  # 仅显式 rollback_to_version
```

repo 级 lease 在短事务中创建。AST、符号解析、关系和 Chunk 构建在写事务外进行，必要时写到任务目录 `.index_staging/`。激活阶段在一个短 `BEGIN IMMEDIATE` 事务中批量写入、校验并切换 active；提交失败保留原 active。相同 repo/input 可有限等待并复用完成版本，不同 input 返回可重试 `index_busy`；SQLite busy 最多重试三次并指数退避。

旧 superseded 快照默认保留，当前版本不自动物理清理历史。显式版本回滚会在一个事务中与当前 active 原子交换；运行数据删除仍必须使用明确的 retention/reset 操作。
