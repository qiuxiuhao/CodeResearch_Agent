# v0.2 开发计划：文件级分析

## 阶段目标

v0.2 在 v0.1.1 的最小闭环基础上增加文件级分析能力：基于 `repo_index.json`、`parsed_files.json` 和 LangGraph State 中已有的 `repo_index`、`parsed_files`、`classes`、`functions`，对每个 Python 文件生成结构化说明，判断文件类型、文件作用、项目位置、主要类和主要函数，输出 `file_analysis.json`，并在 `report.md` 中增加“逐文件分析”章节。

## 本阶段不做什么

不做函数级分析、库函数调用识别、全局 Python 函数知识库、论文解析、论文代码对齐、模型结构识别、模型图、Mermaid 图、前端、RAG、历史任务或复杂任务队列。

## 预计新增和修改的文件

新增：

```text
backend/app/agents/nodes/file_analyze_node.py
backend/app/tools/file_analyze_tool.py
backend/app/schemas/file_analysis.py
backend/app/prompts/file_analyzer.md
tests/test_file_analyze_tool.py
plan/plan_stage2.md
```

修改：

```text
backend/app/schemas/state.py
backend/app/agents/graph.py
backend/app/agents/nodes/report_generate_node.py
backend/app/tools/report_tool.py
tests/test_langgraph_workflow.py
README.md
pyproject.toml
```

不修改：

```text
AGENTS.md
plan/plan_stage1.md
```

## 每个文件的作用

- `file_analysis.py`：定义文件级分析的 Pydantic 模型。
- `file_analyze_tool.py`：提供可单测的确定性文件级分析逻辑。
- `file_analyze_node.py`：LangGraph 节点，写入 `file_analysis` State 字段。
- `file_analyzer.md`：后续 LLM 文件级分析 prompt 规范，v0.2 不接入 LLM。
- `report_generate_node.py`：保存 `file_analysis.json` 并把文件级分析传入报告工具。
- `report_tool.py`：在 Markdown 报告中增加“逐文件分析”章节。

## FileAnalysis 数据结构设计

`FileAnalysis` 包含：

- `file_path`
- `file_type`
- `purpose`
- `project_position`
- `main_classes`
- `main_functions`
- `imports`
- `class_count`
- `function_count`
- `is_entry_file`
- `is_model_file`
- `is_training_file`
- `is_inference_file`
- `is_dataset_file`
- `is_package_init`
- `evidence`
- `confidence`

所有类、函数、import 必须来自 AST 解析结果；所有判断必须写入 `evidence`。

## 文件类型识别规则

按优先级判断：

1. `package_init`：文件名为 `__init__.py`。
2. `entry`：命中入口候选或文件名为 `main.py`、`app.py`、`run.py`、`cli.py`、`__main__.py`。
3. `model`：命中模型候选，或存在继承 `nn.Module` / `torch.nn.Module` 的类，或路径/文件名包含模型相关关键词，但排除 `__init__.py`。
4. `training`：命中训练候选或文件名包含 `train`、`trainer`、`fit`。
5. `inference`：命中推理候选或文件名包含 `infer`、`predict`、`demo`、`eval`。
6. `dataset`：路径包含 `data/`、`dataset`、`datasets`、`loader`、`dataloader`，或类名包含 `Dataset`、`DataLoader`。
7. `config_related`：Python 文件名包含 `config`、`settings`、`argparse`。
8. `utility`：路径或文件名包含 `utils`、`helper`、`common`、`misc`。
9. `ordinary_module`：有类或函数但不符合更具体类型。
10. `unknown`：缺少足够结构信息。

## FileAnalyzeNode 设计

节点位置：

```text
START -> unzip -> repo_scan -> code_parse -> file_analyze -> report_generate -> END
```

输入 State：

```text
repo_index
parsed_files
classes
functions
errors
```

输出 State：

```text
file_analysis
errors
```

节点不保存文件，输出文件由 `ReportGenerateNode` 统一负责。

## file_analyzer prompt 设计

新增 `backend/app/prompts/file_analyzer.md`，说明角色、输入、输出 JSON 格式、禁止事项和示例。v0.2 仅作为规范，不进行 LLM 调用。

## 输出文件设计

新增：

```text
outputs/{task_id}/file_analysis.json
```

结构：

```json
{
  "file_analysis": [],
  "errors": []
}
```

## report.md 更新方式

保留 v0.1.1 报告章节，新增：

```markdown
## 逐文件分析
```

每个文件展示文件类型、文件作用、项目位置、主要类、主要函数和判断依据。不展示函数源码，不做函数内部逻辑解释。

## 测试计划

新增 `tests/test_file_analyze_tool.py`，覆盖模型、包初始化、训练、数据集、入口等文件类型。修改 `tests/test_langgraph_workflow.py`，检查 `file_analysis.json` 存在、分析数量等于 Python 文件数量、报告包含“逐文件分析”。

## 验收标准

- 原 v0.1.1 输出仍存在。
- 新增 `file_analysis.json`。
- 每个 Python 文件都有文件级分析项。
- `models/__init__.py` 是 `package_init`。
- `models/simple_model.py` 是 `model`。
- `data/dataset.py` 是 `dataset`。
- `train.py` 是 `training`。
- `main.py` 是 `entry`。
- `report.md` 包含“逐文件分析”章节。
- `pytest -q` 全部通过。

## 可能风险和解决方案

- 文件类型冲突：使用固定优先级。
- `__init__.py` 被误判：优先识别为 `package_init`。
- 文件分析越界成函数分析：只列函数名，不解释函数内部逻辑。
- 凭空总结：所有结论来自路径、候选列表、imports、classes、functions、base_classes。

## 执行顺序

1. 更新版本到 `0.2.0`。
2. 新增 FileAnalysis schema。
3. 更新 AgentState。
4. 实现确定性 file analysis tool。
5. 新增 prompt 模板。
6. 新增 FileAnalyzeNode。
7. 更新 LangGraph。
8. 更新 ReportGenerateNode 和 report tool。
9. 新增/修改测试。
10. 更新 README。
11. 运行 `conda run -n code-research-agent pytest -q`。
12. 运行示例 ZIP 验收并清理缓存。

