# v0.4 开发计划：全局 Python 函数知识库 MVP

## 1. 阶段目标

v0.4 基于 v0.3.1 已有的 `library_calls` 基础识别能力，新增一个全局可复用的 Python 函数知识库 MVP：

- 使用 SQLite 存储全局库函数解释。
- 使用 SQLite 记录库函数在各分析任务中的出现位置。
- 分析项目时，按 `canonical_name` 查询全局知识库。
- 已存在的库函数解释直接复用。
- 不存在的库函数生成一份教学级、清晰、通俗、简洁的解释并写入 SQLite。
- 将当前任务涉及的库函数解释输出为 `library_function_docs.json`。
- 将库函数出现记录写入 `library_function_occurrences`。
- 更新 `library_calls` 和 `function_analysis` 中的 `is_recorded_in_global_library`。
- 在 `report.md` 中增加“Python 库函数说明”章节。

## 2. 本阶段不做什么

v0.4 不做：

- 不实现前端正常模式 / 零基础模式。
- 不实现库函数弹窗。
- 不实现全局函数库页面。
- 不实现模型结构识别、模型图、Mermaid 图。
- 不实现论文解析或论文代码对齐。
- 不实现 PDF 导出。
- 不引入复杂 RAG、向量数据库或官方文档检索链路。
- 不实现人工编辑库函数解释。
- 不做跨用户权限系统。

## 3. 预计新增和修改的文件

新增文件：

```text
backend/app/schemas/library_function.py
backend/app/services/library_function_service.py
backend/app/agents/nodes/library_function_doc_node.py
backend/app/prompts/library_function_doc_writer.md
tests/test_library_function_service.py
tests/test_library_function_doc_node.py
plan/plan_stage4.md
```

修改文件：

```text
backend/app/schemas/state.py
backend/app/agents/graph.py
backend/app/agents/nodes/report_generate_node.py
backend/app/tools/report_tool.py
backend/app/services/analysis_service.py
tests/test_langgraph_workflow.py
README.md
pyproject.toml
.env.example
.gitignore
```

不修改：

```text
AGENTS.md
plan/plan_stage1.md
plan/plan_stage2.md
plan/plan_stage3.md
```

## 4. 每个文件的作用

- `schemas/library_function.py`：定义 `LibraryFunctionDoc`、`LibraryFunctionOccurrence`、服务返回结果模型。
- `services/library_function_service.py`：负责 SQLite 初始化、查询、插入、复用、出现记录写入。
- `agents/nodes/library_function_doc_node.py`：LangGraph 节点，读取 `library_calls`，调用服务，写入 `library_function_docs`、`new_library_functions`，并更新 `library_calls`。
- `prompts/library_function_doc_writer.md`：定义后续 LLM 生成库函数解释的 prompt 规范；v0.4 MVP 可先用确定性模板生成解释。
- `report_generate_node.py`：保存 `library_function_docs.json`，并将库函数解释传入报告工具。
- `report_tool.py`：在报告中增加“Python 库函数说明”章节。
- `analysis_service.py`：允许通过参数或环境变量指定全局 SQLite 路径，并在 CLI summary 中返回数据库路径与文档数量。
- `.env.example`：新增 `LIBRARY_DB_PATH=data/python_function_library.sqlite3`。
- `.gitignore`：忽略 `data/*.sqlite3`、`data/*.db` 等本地数据库文件，保留 `data/.gitkeep`。

## 5. 数据库设计

MVP 使用 SQLite，默认数据库路径：

```text
data/python_function_library.sqlite3
```

配置优先级：

1. `run_analysis(..., library_db_path=...)` 显式参数。
2. 环境变量 `LIBRARY_DB_PATH`。
3. 默认值 `data/python_function_library.sqlite3`。

数据库初始化由 `LibraryFunctionService.ensure_schema()` 完成。服务首次使用时自动创建表和索引。

必须创建索引：

- `library_functions.canonical_name` 唯一索引。
- `library_function_occurrences.library_function_id` 普通索引。
- `library_function_occurrences.task_id` 普通索引。
- `library_function_occurrences.canonical_name` 普通索引，便于直接按函数名查出现记录。

## 6. `library_functions` 表结构设计

表名：

```text
library_functions
```

字段：

```text
id INTEGER PRIMARY KEY AUTOINCREMENT
canonical_name TEXT NOT NULL UNIQUE
display_name TEXT NOT NULL
package_name TEXT
category TEXT
source_type TEXT NOT NULL
summary TEXT NOT NULL
beginner_explanation TEXT NOT NULL
parameters_explanation TEXT NOT NULL
return_explanation TEXT
common_usage TEXT
code_example TEXT
shape_or_tensor_note TEXT
common_mistakes TEXT NOT NULL
related_functions TEXT NOT NULL
official_doc_url TEXT
confidence TEXT NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

JSON 字段存储策略：

- `parameters_explanation` 存 JSON 字符串数组。
- `common_mistakes` 存 JSON 字符串数组。
- `related_functions` 存 JSON 字符串数组。

v0.4 字段默认：

- `source_type`: `template_generated`
- `confidence`: 根据原始 `LibraryCall.confidence` 继承，高置信库函数一般为 `medium` 或 `high`，低置信函数不自动入库。

## 7. `library_function_occurrences` 表结构设计

表名：

```text
library_function_occurrences
```

字段：

```text
id INTEGER PRIMARY KEY AUTOINCREMENT
library_function_id INTEGER NOT NULL
canonical_name TEXT NOT NULL
task_id TEXT NOT NULL
project_name TEXT
file_path TEXT NOT NULL
function_name TEXT NOT NULL
class_name TEXT
qualified_function_name TEXT NOT NULL
line_no INTEGER
call_text TEXT NOT NULL
created_at TEXT NOT NULL
FOREIGN KEY(library_function_id) REFERENCES library_functions(id)
```

写入规则：

- 每个 `LibraryCall` 对应一条 occurrence。
- 同一次任务中相同函数同一行同一 `call_text` 可以去重。
- occurrence 写入失败不应中断分析，应写入 `errors`。

## 8. LibraryFunctionDoc 数据结构设计

建议模型：

```python
class LibraryFunctionDoc(BaseModel):
    id: int | None = None
    canonical_name: str
    display_name: str
    package_name: str | None = None
    category: str | None = None

    source_type: Literal["template_generated", "manual", "official_doc", "llm_generated"] = "template_generated"
    summary: str
    beginner_explanation: str
    parameters_explanation: list[str] = []
    return_explanation: str | None = None
    common_usage: str | None = None
    code_example: str | None = None
    shape_or_tensor_note: str | None = None
    common_mistakes: list[str] = []
    related_functions: list[str] = []
    official_doc_url: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    created_at: str | None = None
    updated_at: str | None = None
```

补充模型：

```python
class LibraryFunctionOccurrence(BaseModel):
    id: int | None = None
    library_function_id: int
    canonical_name: str
    task_id: str
    project_name: str | None = None
    file_path: str
    function_name: str
    class_name: str | None = None
    qualified_function_name: str
    line_no: int | None = None
    call_text: str
    created_at: str | None = None
```

## 9. LibraryFunctionService 设计

类名：

```python
class LibraryFunctionService:
```

核心方法：

```python
ensure_schema() -> None
get_by_canonical_name(canonical_name: str) -> LibraryFunctionDoc | None
create_doc_from_call(call: dict) -> LibraryFunctionDoc
upsert_library_function_doc(doc: LibraryFunctionDoc) -> LibraryFunctionDoc
record_occurrence(doc: LibraryFunctionDoc, call: dict, task_id: str, project_name: str | None) -> None
process_library_calls(library_calls: list[dict], task_id: str, project_name: str | None) -> LibraryFunctionProcessResult
list_functions(limit: int = 100, package_name: str | None = None) -> list[LibraryFunctionDoc]
list_occurrences(canonical_name: str) -> list[LibraryFunctionOccurrence]
```

`process_library_calls()` 返回：

```python
class LibraryFunctionProcessResult(BaseModel):
    library_function_docs: list[LibraryFunctionDoc]
    new_library_functions: list[LibraryFunctionDoc]
    updated_library_calls: list[dict]
    skipped_low_confidence_calls: list[dict]
    errors: list[dict]
```

服务约束：

- 只使用 Python 标准库 `sqlite3`，不引入 ORM。
- 数据库连接每次操作短连接或上下文管理，避免长连接状态。
- 所有写入使用参数化 SQL。
- 对 `canonical_name` 唯一约束冲突使用查询后复用，不重复生成解释。

## 10. LibraryFunctionDocNode 设计

节点名：

```text
library_function_doc
```

节点位置：

```text
library_call_extract -> function_analyze -> library_function_doc -> report_generate
```

说明：

- 放在 `function_analyze` 之后，便于先完成函数级分析，再统一处理库函数文档。
- 节点处理完后，需要同步更新 `function_analysis[*].library_calls[*].is_recorded_in_global_library`。

输入 State：

```text
task_id
repo_path
library_calls
function_analysis
errors
```

输出 State：

```text
library_function_docs
new_library_functions
low_confidence_library_calls
library_calls
function_analysis
errors
```

节点行为：

- 如果 `library_calls` 为空，写入空 `library_function_docs` 和 `new_library_functions`。
- 对 `confidence == "low"` 或 `category == "unknown"` 的调用不自动入库，只保留在 `low_confidence_library_calls`。
- 对可确认调用查询/写入 SQLite，并记录 occurrences。
- 更新所有已入库调用的 `is_recorded_in_global_library=True`。

## 11. 教学级解释生成规则

v0.4 MVP 使用确定性模板生成解释，不调用外部 LLM，不检索官方文档。

模板根据 `category` 和 `canonical_name` 生成：

- `summary`：一句话说明函数大致用途。
- `beginner_explanation`：用初学者能理解的语言说明。
- `parameters_explanation`：如果无法准确知道参数，写“参数含义需结合具体函数官方文档确认”。
- `return_explanation`：说明通常返回处理后的对象/张量/数组/结果。
- `common_usage`：结合类别说明常见用途。
- `code_example`：只给极简示例，避免不准确复杂用法。
- `shape_or_tensor_note`：PyTorch / NumPy 函数可提示“注意张量/数组形状”。
- `common_mistakes`：给 1-3 条通用误区。
- `related_functions`：v0.4 可为空数组。
- `official_doc_url`：v0.4 可为空，后续版本补官方文档检索。

类别模板：

- `pytorch`：强调 Tensor、模型训练、维度/shape。
- `numpy`：强调数组、数值计算、shape。
- `opencv`：强调图像矩阵、通道顺序。
- `pil`：强调图片读取/处理。
- `einops`：强调张量维度重排。
- `python_stdlib`：强调标准库基础能力。
- `third_party`：说明是第三方库函数，解释置信度中等。

## 12. 新库函数处理流程

流程：

```text
读取 library_calls
  -> 过滤 low/unknown
  -> 按 canonical_name 去重
  -> 查询 library_functions
  -> 不存在则生成 LibraryFunctionDoc
  -> 写入 library_functions
  -> 写入 library_function_occurrences
  -> 更新 library_calls.is_recorded_in_global_library=True
  -> 输出到 library_function_docs.json
```

生成新解释时必须记录：

- `source_type = "template_generated"`
- `created_at`
- `updated_at`
- `confidence`

## 13. 已有库函数复用流程

流程：

```text
读取 library_calls
  -> 按 canonical_name 查询 library_functions
  -> 找到已有 doc
  -> 不重新生成解释
  -> 写入本次 occurrence
  -> 更新 library_calls.is_recorded_in_global_library=True
  -> 将 doc 加入当前任务 library_function_docs
```

验收重点：

- 连续两次分析同一个项目，`torch.randn` 等函数只在 `library_functions` 中出现一次。
- 第二次分析仍会新增 occurrence。

## 14. 低置信度函数处理策略

低置信度规则：

- `LibraryCall.confidence == "low"`。
- `LibraryCall.category == "unknown"`。
- `canonical_name` 无法确认外部包来源。

处理策略：

- 不自动写入 `library_functions`。
- 不生成教学解释。
- 保留在 `library_calls.json.low_confidence_library_calls`。
- 在 `library_function_docs.json` 中增加 `skipped_low_confidence_calls`。
- `report.md` 可简短提示存在低置信度调用，但不解释。

## 15. 输出文件设计

新增输出：

```text
outputs/{task_id}/library_function_docs.json
```

结构：

```json
{
  "library_function_docs": [],
  "new_library_functions": [],
  "skipped_low_confidence_calls": [],
  "errors": []
}
```

更新输出：

- `library_calls.json`
  - 已入库调用的 `is_recorded_in_global_library` 更新为 `true`。
- `function_analysis.json`
  - 每个函数内的 `library_calls` 同步更新 `is_recorded_in_global_library`。
- `report.md`
  - 新增库函数说明章节。

数据库文件：

```text
data/python_function_library.sqlite3
```

数据库文件不提交到版本库。

## 16. report.md 更新方式

新增章节：

```markdown
## Python 库函数说明
```

内容示例：

```markdown
### torch.randn

- 一句话作用：用于生成随机 Tensor。
- 通俗解释：可以理解为创建一组随机数，常用于构造测试输入或初始化数据。
- 常见用途：在 PyTorch 代码中创建随机张量。
- 注意事项：需要关注返回 Tensor 的形状。
```

报告要求：

- 只展示当前任务出现过的库函数。
- 不展示低置信度 unknown 的教学解释。
- 不做前端弹窗或交互。
- 不输出超长文档，保持简洁。

## 17. API 设计，可先做最小接口或暂不暴露

v0.4 推荐做最小只读接口，但可以不做前端页面。

新增文件可选：

```text
backend/app/api/routes_library.py
```

最小接口：

```text
GET /library/functions
GET /library/functions/by-name/{canonical_name}
GET /library/functions/{canonical_name}/occurrences
```

如果为了控制范围暂不暴露 API，则必须保证：

- `LibraryFunctionService` 提供可测试查询方法。
- README 说明 v0.4 暂无前端和页面。

默认执行方案：

- 实现服务层查询方法。
- 暂不接 FastAPI 路由，避免提前进入全局函数库页面或前端阶段。

## 18. 测试计划

新增测试：

```text
tests/test_library_function_service.py
tests/test_library_function_doc_node.py
```

修改测试：

```text
tests/test_langgraph_workflow.py
```

单元测试场景：

- 首次处理 `torch.randn` 会创建 `library_functions` 记录。
- 再次处理 `torch.randn` 不重复创建 doc。
- 每次处理都会写入 occurrence。
- `confidence=low` 或 `category=unknown` 的调用不入库。
- `LibraryFunctionDoc` 能从 SQLite 正确读取并还原 list 字段。
- occurrence 包含 task_id、file_path、function_name、line_no、call_text。

集成测试场景：

- 完整 workflow 输出 `library_function_docs.json`。
- `library_calls.json` 中确认入库的调用 `is_recorded_in_global_library=True`。
- `function_analysis.json` 中嵌套的 library calls 同步为 `True`。
- `report.md` 包含“Python 库函数说明”章节。
- 使用临时 SQLite 路径，测试不污染真实 `data/python_function_library.sqlite3`。

运行命令：

```bash
conda run -n code-research-agent pytest -q
```

## 19. 验收标准

v0.4 完成后必须满足：

- 使用 SQLite 存储 `library_functions`。
- 使用 SQLite 存储 `library_function_occurrences`。
- 同一个 `canonical_name` 不重复生成解释。
- 同一个函数跨任务复用已有解释。
- 新任务仍能记录新的 occurrence。
- 低置信度/unknown 调用不自动入库。
- 输出 `library_function_docs.json`。
- `library_calls.json` 和 `function_analysis.json` 中已入库调用标记为 `is_recorded_in_global_library=True`。
- `report.md` 包含“Python 库函数说明”章节。
- `pytest -q` 全部通过。
- 不实现前端、模型识别、论文解析、PDF、RAG 或全局函数库页面。

## 20. 可能风险和解决方案

风险：模板解释不够准确。  
解决方案：明确 `source_type=template_generated`，解释保持通用，不编造具体参数细节；官方文档检索放后续版本。

风险：低置信度函数污染全局知识库。  
解决方案：`low` 或 `unknown` 默认不入库，只输出 skipped 列表。

风险：SQLite 重复写入同一函数。  
解决方案：`canonical_name` 唯一约束，写入前查询，冲突后复用已有记录。

风险：occurrence 重复过多。  
解决方案：同一任务、同一 canonical_name、同一 file_path、同一 qualified_function_name、同一 line_no、同一 call_text 可去重。

风险：数据库文件被误提交。  
解决方案：`.gitignore` 忽略 `data/*.sqlite3`、`data/*.db`，只保留 `data/.gitkeep`。

风险：服务层和 LangGraph State 不一致。  
解决方案：`LibraryFunctionDocNode` 是唯一更新 `library_function_docs` 和入库状态的地方。

风险：报告内容过长。  
解决方案：每个库函数只展示一句话作用、通俗解释、常见用途和注意事项。

## 21. 执行顺序

1. 更新版本到 `0.4.0`。
2. 新增 `data/.gitkeep`，更新 `.gitignore` 忽略 SQLite 文件。
3. 新增 `LibraryFunctionDoc`、`LibraryFunctionOccurrence`、处理结果 schema。
4. 实现 `LibraryFunctionService`，包含 schema 初始化、查询、写入、occurrence 记录。
5. 实现教学级解释模板生成逻辑。
6. 新增 `LibraryFunctionDocNode`。
7. 更新 `AgentState`，增加 `library_function_docs`、`new_library_functions`、`skipped_low_confidence_library_calls`。
8. 更新 LangGraph，将 `library_function_doc` 插入 `function_analyze` 和 `report_generate` 之间。
9. 更新 `ReportGenerateNode`，保存 `library_function_docs.json`，并保存更新后的 `library_calls` / `function_analysis`。
10. 更新 `report_tool.py`，增加“Python 库函数说明”章节。
11. 更新 `analysis_service.py`，支持数据库路径配置并在 summary 中返回路径。
12. 新增服务层和节点测试。
13. 更新 workflow 集成测试。
14. 更新 README 和 `.env.example`。
15. 使用临时 SQLite 路径运行 `pytest -q`。
16. 运行示例 ZIP，检查 JSON、SQLite、报告输出。
17. 清理 `.pytest_cache/`、`__pycache__/`、`*.pyc`、`code_research_agent.egg-info/`。
