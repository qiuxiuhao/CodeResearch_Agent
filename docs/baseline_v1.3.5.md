# CodeResearch Agent v1.3.5 基线记录

记录日期：2026-07-17  
工作分支：`upgrade/v1.4-structured-index`

## 1. Git 基线

- Commit：`5073f9f899e83759a6e21ec1ea56a7ae282f84eb`
- 最近提交：`5073f9f docs: update project roadmap for v1.4 to v2.0`
- 基线检查前 `git status --short` 无输出，工作区干净。
- 完整验收完成后再次执行 `git status --short`，仍无输出。
- 本次审计未创建 Git commit。

## 2. 运行环境

所有 Python 和 Node 验收命令均在 Conda 环境 `code-research-agent` 中运行。

| 组件 | 实际版本 |
| -- | -- |
| Python | 3.11.15 |
| Node.js | v24.15.0 |
| 项目版本 | 1.3.5 |
| 前端包版本 | 1.3.5 |

## 3. 基线测试结果

### 3.1 后端测试

命令：

```bash
python -m pytest -q
```

结果：通过。

```text
218 passed, 6 warnings in 43.61s
```

### 3.2 前端测试

命令：

```bash
npm --prefix frontend test
```

结果：通过。

```text
Test Files  16 passed (16)
Tests       29 passed (29)
Duration    1.21s
```

### 3.3 前端构建

命令：

```bash
npm --prefix frontend run build
```

结果：通过。

- TypeScript app 和 Vite config 的 no-emit typecheck 通过。
- Vite 处理 3,695 个模块并成功生成生产构建。
- 构建契约通过：Mermaid 保持动态加载，TypeScript 未生成配置 JS、声明文件或 `tsbuildinfo`。

### 3.4 完整验收

命令：

```bash
bash scripts/validate.sh
```

结果：通过。脚本实际完成：

- 后端：218 passed，6 warnings，46.98s。
- `npm ci`：成功安装 272 个包。
- 前端：16 个测试文件、29 个测试全部通过。
- 前端生产构建及构建契约通过。
- 脚本最终输出 `Validation completed.`。

## 4. 已知警告

本次没有测试或构建失败。实际观察到以下警告：

1. PyMuPDF/SWIG 类型 `SwigPyPacked`、`SwigPyObject`、`swigvarlink` 缺少 `__module__` 的 `DeprecationWarning`。
2. FastAPI `TestClient` 触发 Starlette 警告：当前通过 `httpx` 使用 `starlette.testclient` 的方式已弃用。
3. `npm ci` 报告 `whatwg-encoding@3.1.1` 已弃用。
4. Vite 报告部分构建 chunk 超过 500 kB；其中 `mermaid.core` 约 621.39 kB，`cynefin` 约 687.89 kB。
5. `npm ci` 提示 31 个包可接受 funding。

这些警告未导致 v1.3.5 基线验收失败，本次审计也未修改代码处理它们。

## 5. 当前核心工作流

`backend/app/agents/graph.py` 定义 21 个顺序节点；LangGraph 不可用时 `_SequentialGraph` 保持相同顺序：

```text
unzip
→ repo_scan
→ code_parse
→ file_analyze
→ library_call_extract
→ function_analyze
→ model_analyze
→ paper_analyze
→ paper_figure_extract
→ paper_code_align
→ file_explain_llm
→ function_explain_llm
→ model_explain_llm
→ paper_figure_analyze_vlm
→ paper_code_align_llm
→ diagram_generate
→ teaching_diagram_plan
→ teaching_diagram_generate
→ teaching_diagram_review_vlm
→ library_function_doc
→ report_generate
```

核心调用链如下：

1. `analysis_service.run_analysis()` 解析运行选项、创建 Provider runtime，并初始化 `AgentState`。
2. `unzip_node` 将 ZIP 安全解压到 `outputs/{task_id}/source`。
3. `repo_scan_node` 调用 `scan_repository()`，生成文件树、Python 文件列表和入口/模型/训练/推理/配置候选。
4. `code_parse_node` 调用 `parse_python_files()`，以 Python AST 生成 `ParsedFile`、`FunctionInfo` 和 `ClassInfo`。
5. 文件、库调用、函数和模型分析节点依次消费这些规则事实。
6. 可选论文节点解析 PDF、提取 Figure，并以启发式规则完成论文代码对齐。
7. LLM/VLM 节点在规则事实之后生成独立解释或建议，受开关、授权、预算和缓存约束。
8. `report_generate_node` 保存 JSON 结果并生成 `report.md`。

## 6. 当前 AST 与分析数据结构

### 6.1 AST 解析结果

`backend/app/schemas/code.py` 定义：

- `ImportInfo`：`module`、`name`、`alias`、`import_type`、`line_no`。
- `FunctionInfo`：文件路径、函数名、所属类、参数、起止行、源码和 `raw_call_expressions`。
- `ClassInfo`：文件路径、类名、基类、起止行和直接方法名。
- `ParsedFile`：文件路径、imports、aliases、classes、functions 和 errors。

`ast_parse_tool._AstCollector` 的实际行为：

- `import x` 和 `import x as y` 保存 import 记录，并把本地可见名称映射到真实 module。
- `from x import y` 和 alias 保存 module/name/alias；相对导入层级编码在 module 的前导 `.` 中。
- class 保存 `ast.unparse()` 得到的基类文本、方法名和 AST 行号范围。
- function 和 async function 保存参数、源码、类上下文和行号。
- 函数内所有 `ast.Call` 的 `call.func` 经 `ast.unparse()` 后进入 `raw_call_expressions`。
- 单文件语法或编码错误被写入 errors，不终止其他文件解析。

### 6.2 `raw_call_expressions` 的消费

- `library_call_extractor_tool` 重新解析函数源码，结合 aliases 和项目符号排除明显内部调用，并识别外部库调用。
- `function_analyze_tool` 用它生成计算逻辑、内部调用候选和核心函数启发式判断。
- `model_detect_tool` 重新解析 `__init__` 与 `forward` 源码，识别 `self.<name>` 层、调用顺序和模型数据流。
- 当前没有仓库级 Symbol Table、Import Resolver 或 Call Graph；内部调用列表仍是启发式字符串结果。

### 6.3 可直接复用的现有 Schema

- AST 事实：`ParsedFile`、`ImportInfo`、`ClassInfo`、`FunctionInfo`。
- 文件与函数事实：`FileAnalysis`、`FunctionAnalysis`、`LibraryCall`。
- 模型事实：`ModelAnalysis`、`ModelLayer`、`ForwardStep`、`ModelComponentCandidate`。
- 论文事实：`PaperAnalysis`、`PaperSection`、`PaperContribution`、`PaperFigure`、`FigureCaption`、`FigureAsset`。
- 现有论文代码对齐中的 `PaperCodeTarget` 可作为新关系构建的规则输入，但不等同于统一实体或关系模型。

## 7. AgentState 中与索引构建相关的现有字段

当前 `AgentState` 没有统一索引字段。可供后续索引构建消费的现有字段包括：

- 输入和路径：`task_id`、`zip_path`、`paper_pdf_path`、`repo_path`、`output_dir`。
- 扫描事实：`file_tree`、`python_files`、`repo_index`。
- AST 事实：`parsed_files`、`functions`、`classes`。
- 规则分析：`file_analysis`、`library_calls`、`function_analysis`、`model_analysis`。
- 论文事实：`paper_analysis`、`paper_figure_analysis`、`paper_code_alignment`。
- 运行错误：`errors`。

LLM/VLM explanation、budget、provider config 和 teaching diagram 字段不是确定性代码索引的事实来源。

## 8. 当前输出文件及依赖

`report_generate_node` 当前写出：

| 文件 | 主要来源/依赖 |
| -- | -- |
| `repo_index.json` | 仓库扫描结果 |
| `parsed_files.json` | parsed files、classes、functions、errors |
| `file_analysis.json` | 文件规则分析、errors |
| `library_calls.json` | 库调用、高低置信度分类、errors |
| `function_analysis.json` | 函数规则分析、errors |
| `model_analysis.json` | 模型规则分析、errors |
| `paper_analysis.json` | 论文规则解析、errors |
| `paper_code_alignment.json` | 规则论文代码对齐、errors |
| `paper_figure_analysis.json` | 本地 Figure 提取及可选 VLM 结果 |
| `diagrams.json` | Mermaid 图、warnings、errors |
| `library_function_docs.json` | 全局库函数说明及写库结果 |
| `llm_explanations.json` | 独立 LLM 解释、证据目录、预算和警告 |
| `ai_usage.json` | 五类 AI 能力使用摘要 |
| `teaching_diagrams/manifest.json` | 教学图资产、预算、状态和警告 |
| `report.md` | 规则分析报告，并附加可用的 LLM/VLM/教学图章节 |

任务目录还可能包含：

- `source/`：安全解压后的仓库文件。
- `paper_figures/`：论文 Figure 原始资产和 canonical preview。
- `teaching_diagrams/`：Skeleton、Spec、Blueprint、AI 图和审查产物。

`analysis_service.TASK_RESULT_FILES` 控制 API 读取哪些结果。前端 `AnalysisResult` 继续按上述旧结果字段展示总览、文件、函数、库函数、模型、论文、图示、教学图和报告。

## 9. 当前数据库用途

当前没有仓库结构化索引数据库。审计到的 SQLite 用途是：

| 数据库/组件 | 实际表 | 用途 |
| -- | -- | -- |
| `data/python_function_library.sqlite3` | `library_functions` | 跨任务复用 Python/PyTorch 等库函数教学说明 |
| `data/llm_explanation_cache.sqlite3` | `llm_cache` | 文本 LLM 响应缓存 |
| `VisionCache` 配置的数据库 | `vision_cache_v2` | Figure VLM 响应缓存 |
| `data/image_generation_cache.sqlite3` | `image_generation_cache` | 图片生成缓存和资产引用 |
| `TeachingDiagramReviewCache` 配置的数据库 | `teaching_diagram_review_cache` | 教学图审查缓存 |

实际检查到的三个 `data/*.sqlite3` 数据库 `PRAGMA user_version` 均为 `0`。代码通过 `CREATE TABLE IF NOT EXISTS` 延迟建表，没有编号 migration、升级状态表或统一迁移执行器。

## 10. 事实与模型解释边界

确定性事实来源包括仓库扫描、Python AST、文件/函数/模型规则、PDF 文本与 Figure 本地提取、规则论文代码对齐和本地 Mermaid/Blueprint 构建。

以下内容属于模型解释或建议，不得覆盖规则事实：

- 文件、函数和模型 LLM explanation。
- 论文代码对齐 LLM explanation 及 suggested code links。
- Figure VLM 的类型、摘要、模块与流程解释。
- 教学图 LLM narrative、AI 图片和 VLM review。

## 11. 可作为 v1.4.0 回归基线的测试

- `test_ast_parse_tool.py`：imports、alias、class、function、line range、raw calls 和语法错误。
- `test_repo_scan_tool.py`：仓库文件扫描、候选文件和忽略目录。
- `test_file_analyze_tool.py`：文件类型与职责规则。
- `test_library_call_extractor_tool.py`：alias、内部调用排除和低置信度外部调用。
- `test_function_analyze_tool.py`：函数调用、核心函数和去重逻辑。
- `test_model_detect_tool.py`：`nn.Module`、层、forward 步骤和分支警告。
- `test_paper_parse_tool.py`、`test_paper_figure_extract_tool.py`、`test_paper_code_align_tool.py`：论文事实、Figure 稳定 ID 和规则对齐。
- `test_langgraph_workflow.py`：完整工作流、旧输出文件、报告和 SQLite 复用。
- `test_api_results.py`：旧任务结果读取及缺失文件兼容。
- `test_example_archive_contract.py`：示例源码与 ZIP 的确定性一致性。
- 全部 LLM/VLM/Teaching Diagram 测试：规则事实、授权、预算、缓存和 fallback 不回退。

## 12. v1.4.0 必须保持兼容的能力

1. 纯规则、离线、无 Provider Key 的完整分析和报告。
2. ZIP 安全解压、路径逃逸防护和单文件失败隔离。
3. 现有 21 节点相对顺序及顺序 fallback；v1.4 只允许增量插入独立索引节点。
4. `parsed_files.json`、`file_analysis.json`、`function_analysis.json` 等旧文件继续生成。
5. 旧输出字段的 Schema、类型、含义和规范化语义兼容；不要求字节序列完全一致。
6. 旧报告生成逻辑和现有前端展示不依赖新索引即可继续工作。
7. 正常模式、零基础模式、库函数说明、模型分析、论文、Figure、Mermaid、教学图和 Provider 设置不回退。
8. LLM/VLM 解释保持独立、可关闭、需授权且不能改变规则事实。
9. 自动测试不访问真实 Provider 或付费网络服务。

