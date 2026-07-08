# v0.3 开发计划：函数级分析 + library_calls 基础识别

## 阶段目标

v0.3 基于 v0.2.1 的 `repo_index.json`、`parsed_files.json`、`file_analysis.json`，新增函数级分析与基础库函数调用识别能力：为每个 Python 函数/方法生成结构化说明，识别函数内部调用的 Python / PyTorch / NumPy / OpenCV / PIL / einops 等外部库函数，输出 `function_analysis.json` 和 `library_calls.json`，并在 `report.md` 中增加“逐函数分析”章节。

## 本阶段不做什么

不做全局 Python 函数知识库、库函数入库、SQLite 存储、库函数教学解释、论文解析、论文代码对齐、模型结构识别、模型图、前端零基础模式、PDF 导出、RAG、历史任务或复杂任务队列。

## 预计新增和修改的文件

新增：

```text
backend/app/schemas/library_call.py
backend/app/schemas/function_analysis.py
backend/app/tools/library_function_resolver_tool.py
backend/app/tools/library_call_extractor_tool.py
backend/app/tools/function_analyze_tool.py
backend/app/agents/nodes/library_call_extract_node.py
backend/app/agents/nodes/function_analyze_node.py
backend/app/prompts/function_analyzer.md
tests/test_library_function_resolver_tool.py
tests/test_library_call_extractor_tool.py
tests/test_function_analyze_tool.py
plan/plan_stage3.md
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
plan/plan_stage2.md
```

## 核心设计

- `library_call_extract` 节点位于 `file_analyze` 之后，负责基础库函数识别。
- `function_analyze` 节点位于 `library_call_extract` 之后，负责生成函数级结构化分析。
- `report_generate` 统一保存 `library_calls.json`、`function_analysis.json` 并更新报告。
- v0.3 不调用 LLM；`function_analyzer.md` 只作为后续扩展规范。

## 数据结构

`LibraryCall` 保存函数位置、标准函数名、显示名、包名、分类、调用文本、行号、置信度和 `is_recorded_in_global_library=False`。

`FunctionAnalysis` 保存函数位置、作用、输入输出、实现逻辑、计算逻辑、模型位置、内部调用、库函数调用、核心函数标记、核心依据、初学者解释和证据。

## 识别规则

- import alias 由 `parsed_file["aliases"]` 解析。
- 支持 `torch`、`torch.nn.functional as F`、`numpy as np`、`cv2 as cv`、`from PIL import Image`、`from einops import rearrange`。
- 排除 `self.*`、`cls.*`、`super()`、项目内部 class/function、Python 常见内置函数。
- 无法确认的调用保留原始名并标记低置信度。

## 输出文件

新增：

```text
outputs/{task_id}/library_calls.json
outputs/{task_id}/function_analysis.json
```

继续保留：

```text
repo_index.json
parsed_files.json
file_analysis.json
report.md
```

## 测试计划

- resolver 测试 alias 还原。
- extractor 测试库函数识别与内部函数排除。
- function analyzer 测试核心函数识别和 `library_calls` 嵌入。
- workflow 测试输出文件、数量、关键函数、报告章节。

## 验收标准

- 每个 Python 函数/方法都有一个 `FunctionAnalysis`。
- `SimpleNet.forward` 能识别 `torch.nn.functional.relu`。
- `train_one_epoch` 能识别 `torch.randn`。
- `SimpleNet(...)`、`train_one_epoch(...)`、`self.fc1(...)` 不作为库函数。
- `report.md` 包含“逐函数分析”章节。
- `pytest -q` 全部通过。

## 执行顺序

1. 更新版本到 `0.3.0`。
2. 新增 schemas、resolver、extractor、function analyzer。
3. 新增 LangGraph 节点并接入工作流。
4. 更新输出保存和报告渲染。
5. 新增/更新测试和 README。
6. 运行测试和示例 ZIP。
7. 清理缓存和构建产物。

