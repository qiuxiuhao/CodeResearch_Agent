# 架构说明

CodeResearch Agent 是一个本地优先的代码理解系统，面向深度学习代码仓库和可选论文 PDF。v1.4.0 保持确定性规则流程为事实来源，在其上新增可选的仓库级结构化索引；文本 LLM、论文 VLM 和图片生成仍是独立授权的解释层，不能覆盖索引事实。

## 分层结构

- FastAPI API 层：负责任务创建、文件上传、结果读取、报告读取和全局函数库查询。
- LangGraph 工作流层：编排仓库解压、解析、分析、文档生成、图生成和报告生成。
- Tool 工具层：提供确定性的静态分析工具，包括仓库扫描、AST 解析、模型识别、论文解析、论文代码对齐、Mermaid 生成和报告构建。
- Service 服务层：`analysis_service` 负责单次分析任务编排，`library_function_service` 管理 SQLite 全局 Python 函数知识库。
- Schema 数据层：使用 Pydantic 定义仓库、文件、函数、模型、论文、图示和库函数等稳定 JSON 结构。
- Frontend 前端层：React + Vite 工作台，支持任务创建、结果浏览、零基础解释、图示展示和全局函数库检索。
- LLM 增强层：Provider、ModelRouter、BudgetManager、隐私过滤、evidence catalog 和 SQLite 缓存；业务节点不直接调用供应商。
- Figure 提取层：PyMuPDF 本地检测 caption、页码、bbox、正文引用和原始资产，并渲染 canonical preview。
- Vision 增强层：独立 VisionProvider、VisionModelRouter、预算和缓存；默认 Qwen-VL，备用 GLM-4.5V。
- Provider 配置层：`provider_registry` 是字段、默认值和 UI > Environment > Default 来源优先级的唯一事实源；语义非法的持久化 UI 字段被单字段忽略并脱敏告警，Secret 与 Runtime 不进入任务状态。
- 运行时选项层：`ResolvedAnalysisOptions` 只保存 JSON 安全的能力开关与授权；`ProviderRuntimeContext` 仅在进程内持有 Router/Provider 资源。
- Domain 领域层：`backend/app/domain/` 定义 `CodeEntity`、`PaperEntity`、`KnowledgeEdge`、`EvidenceRef`、`SymbolChunk`、`IndexedFile` 和 `IndexManifest`。
- Indexing 索引层：`backend/app/indexing/` 负责路径/模块根规范化、稳定 ID、input hash、Symbol Table、Import Resolver、继承与调用关系、论文对齐边和 Symbol-aware Chunk。
- Persistence 持久化层：`backend/app/persistence/` 使用编号 SQL migration、repo 级 lease、staging 和短事务原子激活结构化索引版本。

## 数据流

1. 用户提供 ZIP 文件路径，或通过浏览器上传 ZIP。
2. 用户可以可选提供论文 PDF。
3. 后端创建任务，并把 ZIP 解压到 `outputs/{task_id}/source`。
4. LangGraph 先生成旧版规则 JSON 事实，并完成规则论文代码对齐。
5. 开启 `structured_index_enabled` 时，`structured_index_build` 在所有 LLM/VLM 增强前从旧事实增量构建实体、关系、证据、Chunk 和文件快照。
6. 索引在 SQLite 写事务外完成计算和 staging；验证通过后使用一个短 `BEGIN IMMEDIATE` 事务写入并切换 active 版本，随后原子写出 `index_manifest.json`。
7. 文本 LLM 在规则事实和索引之后增强文件、函数、模型和论文对齐解释；Figure VLM 仍只读取授权后的 canonical preview。
8. 报告节点继续按旧逻辑写入 `report.md`，API 和前端继续读取旧任务产物；索引失败只追加结构化错误，不阻断旧报告。
9. 库函数解释持久化到原有 SQLite，结构化索引使用独立数据库，互不迁移或复用表。

## 索引身份与兼容边界

- 显式 `repository_key` 经 Unicode NFC 和 trim 后生成稳定 `repo_id`；未提供时 `repo_id` 包含 `task_id`，禁止按 ZIP 名跨任务合并。
- 路径为仓库相对 POSIX 路径，保留大小写。显式 package root 优先于 `src/`，`src/` 优先于仓库根；仓库根下的目录包要求完整 `__init__.py` 链。
- 实体 ID 不含内容哈希和行号；内容变化由 `content_hash` 与新 `input_hash` 表达，文件移动按删除旧实体并创建新实体处理。
- 同一逻辑 Edge 聚合多条 `EvidenceRef`；无法安全解析的调用仍落为 target-less unresolved/ambiguous Edge。
- 兼容标准是旧文件、字段 Schema、类型、含义和规范化语义不变，不承诺 JSON 字节、空白、键顺序或数组物理编码相同。

## 运行时产物

项目有意不提交生成数据：

- `outputs/task_*`
- `data/*.sqlite3`
- `frontend/node_modules`
- `frontend/dist`
- Python 缓存和 egg-info 元数据

日常 `clean.sh` 只删除可重建产物，不触碰 `data/` 和 `outputs/`。需要永久删除 SQLite 运行数据和 `outputs/task_*` 时，必须使用带显式确认参数的独立重置命令。详见 [验收说明](validation.md)。
