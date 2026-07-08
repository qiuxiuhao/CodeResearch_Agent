# v0.7 开发计划：图生成增强

## 1. 阶段目标

v0.7 基于 v0.6.1 已有的代码仓库分析、函数分析、模型网络识别、论文解析和论文代码对齐结果，新增 Mermaid 图生成能力：

- 基于 `repo_index.json`、`file_analysis.json`、`function_analysis.json`、`model_analysis.json`、`paper_analysis.json`、`paper_code_alignment.json` 生成可读、可追溯的 Mermaid 图。
- 生成项目结构图、模型整体流程图、核心模块图、函数逻辑图、论文创新点到代码实现对应图。
- 输出 `diagrams.json`。
- 在 `report.md` 中增加“图示分析”章节。
- 图节点必须尽量来自真实代码结构、模型分析结果或论文对齐结果。
- 缺少信息时生成简化图，并在图说明中标注“不确定”或“基础静态分析结果”。

## 2. 本阶段不做什么

v0.7 不做：

- 不实现前端页面。
- 不实现 PDF 导出。
- 不实现 Mermaid 渲染为 PNG / SVG。
- 不引入 Graphviz 或复杂图布局引擎。
- 不解析论文图表、公式、表格或图片。
- 不引入复杂 RAG、embedding 检索或向量数据库。
- 不调用 LLM。
- 不执行用户代码，不 import ZIP 中的代码。
- 不凭空生成代码中不存在的模块。
- 不追求复杂炫酷图，优先清楚、稳定、适合报告展示。

## 3. 预计新增和修改的文件

新增文件：

```text
backend/app/schemas/diagram.py
backend/app/tools/mermaid_tool.py
backend/app/agents/nodes/diagram_generate_node.py
backend/app/prompts/diagram_generator.md
tests/test_mermaid_tool.py
tests/test_diagram_generate_node.py
plan/plan_stage7.md
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
backend/app/main.py
```

不修改：

```text
AGENTS.md
plan/plan_stage1.md
plan/plan_stage2.md
plan/plan_stage3.md
plan/plan_stage4.md
plan/plan_stage5.md
plan/plan_stage6.md
```

## 4. 每个文件的作用

- `schemas/diagram.py`：定义图、节点、边、来源引用、图类型、置信度等 Pydantic 模型。
- `tools/mermaid_tool.py`：实现确定性的 Mermaid 图生成逻辑，可单独测试。
- `agents/nodes/diagram_generate_node.py`：LangGraph 节点，读取已有分析结果，写入 `state["diagrams"]`。
- `prompts/diagram_generator.md`：后续 LLM 图生成增强规范；v0.7 不调用 LLM。
- `report_generate_node.py`：保存 `diagrams.json`，并把 diagrams 传给报告工具。
- `report_tool.py`：新增“图示分析”章节，展示 Mermaid 代码块和说明。
- `analysis_service.py`：summary 返回 `diagrams_path`、`diagram_count`。
- `main.py`、`pyproject.toml`、`README.md`：同步版本到 `0.7.0` 并说明新增图输出。
- `tests/*diagram*`：覆盖工具和节点。
- `tests/test_langgraph_workflow.py`：覆盖完整 workflow 输出 `diagrams.json` 和报告章节。

## 5. Diagram 数据结构设计

新增 `backend/app/schemas/diagram.py`，包含：

- `DiagramSourceRef`：记录图节点或边来自哪个结构化产物、文件、类、函数、行号、论文贡献和证据。
- `DiagramNode`：记录节点 ID、显示标签、节点类型、来源引用、置信度和不确定性。
- `DiagramEdge`：记录边的起点、终点、标签、来源引用、置信度和不确定性。
- `Diagram`：记录图 ID、标题、类型、说明、Mermaid 源码、节点、边、来源、警告和置信度。
- `DiagramGenerationResult`：记录所有图、全局警告和错误。

输出 `diagrams.json` 顶层结构：

```json
{
  "diagrams": [],
  "warnings": [],
  "errors": []
}
```

## 6. Mermaid 图生成规则

- 只生成 Mermaid 源码，不渲染图片。
- 使用 `flowchart TD` 或 `flowchart LR`。
- 节点 ID 必须稳定、ASCII、安全。
- 节点 label 必须转义双引号、方括号和换行。
- 单张图建议不超过 20 个节点，超出时截断并写 warning。
- 确定边使用 `-->`。
- 不确定边使用 `-.->`。
- Mermaid 源码不包含 Markdown fence，报告中再包成 `mermaid` 代码块。
- 重复节点按 `id` 去重。
- 重复边按 `source + target + label` 去重。

## 7. 项目结构图设计

图类型：`project_structure`

输入：

- `repo_index.python_files`
- `file_analysis.file_type`
- `file_analysis.purpose`
- `file_analysis.main_classes`
- `file_analysis.main_functions`

生成规则：

- 根节点为 `Project`。
- 按文件类型分组：入口、模型、训练、推理、数据集、配置、工具、普通模块。
- Python 文件作为节点。
- 文件节点连接主要类和主要函数节点。
- 最多展示前 20 个 Python 文件。
- 文件较多时写 warning。

## 8. 模型整体流程图设计

图类型：`model_flow`

输入：

- `model_analysis[*]`
- `layers`
- `forward_steps`
- `model_inputs`
- `model_outputs`
- `component_candidates`

生成规则：

- 优先选择 `is_main_model_candidate=True` 的模型。
- 输入参数作为起点。
- 按 `forward_steps.order` 生成数据流。
- `forward_steps.uses_layers` 命中层名时连到对应层节点。
- 库函数调用可作为计算节点。
- 返回表达式作为输出节点。
- forward 步骤不足时退化为 `inputs -> layers -> outputs` 的简化图。

## 9. 核心模块图设计

图类型：`core_modules`

输入：

- `model_analysis.component_candidates`
- `model_analysis.layers`
- `function_analysis.is_core_function`
- `file_analysis.file_type`

生成规则：

- 模型类连接组件候选。
- 组件候选展示角色，例如 encoder、decoder、backbone、head、classifier、loss、activation。
- 核心函数作为节点。
- model / training / dataset 文件作为上下文节点。
- 无模型组件候选时生成核心函数和核心文件的简化模块图。

## 10. 函数逻辑图设计

图类型：`function_logic`

输入：

- `function_analysis`
- `library_calls`
- `called_internal_functions`
- `implementation_logic`
- `is_core_function`

生成规则：

- 只为最多 3 个核心函数生成图。
- 优先选择核心函数、`forward`、`train`。
- 节点顺序为函数、实现步骤、内部调用、库函数调用、输出。
- 没有实现逻辑时生成简化图并写 warning。

## 11. 论文创新点到代码实现对应图设计

图类型：`paper_code_alignment`

输入：

- `paper_analysis.contributions`
- `paper_code_alignment.alignment_items`
- `matched_targets`
- `unmatched_contributions`

生成规则：

- 无论文时跳过该图，并写全局 warning。
- contribution 作为左侧节点。
- matched target 作为右侧节点。
- medium/high confidence 使用实线。
- low confidence 使用虚线。
- unmatched contribution 不强行连接代码目标。
- 最多展示 5 条 contribution，每条最多 5 个 target。

## 12. DiagramGenerateNode 设计

节点名：

```text
diagram_generate
```

节点位置：

```text
paper_code_align -> diagram_generate -> library_function_doc -> report_generate
```

输入 State：

```text
repo_index
file_analysis
function_analysis
model_analysis
paper_analysis
paper_code_alignment
library_calls
errors
```

输出 State：

```text
diagrams
diagram_warnings
errors
```

## 13. mermaid_tool 设计

新增 `backend/app/tools/mermaid_tool.py`。

核心函数：

```python
def generate_diagrams(
    repo_index: dict,
    file_analysis: list[dict],
    function_analysis: list[dict],
    model_analysis: list[dict],
    paper_analysis: dict,
    paper_code_alignment: dict,
    library_calls: list[dict],
) -> DiagramGenerationResult:
    ...
```

实现约束：

- 只使用标准库和现有 Pydantic schema。
- 不调用 LLM。
- 不联网。
- 不渲染图片。
- 不执行用户代码。
- Mermaid 输出必须可预测。
- 所有节点和边尽量包含 `source_refs`。

## 14. diagrams.json 输出设计

新增输出：

```text
outputs/{task_id}/diagrams.json
```

最少尝试生成：

- `project_structure`
- `core_modules`
- `paper_code_alignment`，如果有论文
- `model_flow`，如果有模型
- `function_logic_*`，如果有核心函数

## 15. report.md 更新方式

在“论文解析与论文代码对齐”之后、“Python 库函数说明”之前新增：

```markdown
## 图示分析
```

报告展示每张图的标题、说明、Mermaid 代码块、警告和来源摘要。不展示完整 nodes / edges JSON。

## 16. 图节点可追溯性设计

- 文件节点来自 `file_analysis`。
- 类节点来自 `model_analysis` 或 AST class 信息。
- 函数节点来自 `function_analysis`。
- 模型层节点来自 `model_analysis.layers`。
- 论文贡献节点来自 `paper_analysis.contributions`。
- 对齐边来自 `paper_code_alignment.alignment_items`。
- 不确定关系设置 `confidence=low` 或 `is_uncertain=True`。

## 17. 测试计划

- `tests/test_mermaid_tool.py`：覆盖项目结构图、模型流程图、核心模块图、函数逻辑图、论文对齐图、无论文 warning、label 转义、节点/边去重和 source refs。
- `tests/test_diagram_generate_node.py`：覆盖节点写入 diagrams、空输入不崩溃、保留 State 字段。
- `tests/test_langgraph_workflow.py`：覆盖 `diagrams.json`、报告“图示分析”章节、无论文和有论文两条路径。

## 18. 验收标准

- 版本号为 `0.7.0`。
- `AgentState` 包含 `diagrams` 和 `diagram_warnings`。
- LangGraph 包含 `diagram_generate` 节点。
- 输出 `diagrams.json`。
- `diagrams.json` 至少包含项目结构图。
- 示例项目中模型流程图包含 `SimpleNet`、`self.fc1`、`self.fc2` 或对应 forward 节点。
- 有论文 PDF 时论文-代码图包含 contribution 节点和 matched target 节点。
- 无论文 PDF 时完整流程仍成功。
- `report.md` 包含“图示分析”章节和 Mermaid 代码块。
- 原有 v0.6.1 输出继续保留。
- `pytest -q` 全部通过。

## 19. 可能风险和解决方案

- Mermaid 特殊字符导致语法不稳定：统一转义并测试。
- 图过大导致报告不可读：限制节点数量并写 warning。
- 图边被误解为运行时调用：明确标注基础静态分析，不确定边用虚线。
- 模型 forward 动态逻辑复杂：只使用 v0.5 已识别的 `forward_steps`。
- 论文对齐误导：只展示已有 matched targets，不强行连接 unmatched contribution。
- 无模型或无论文：至少生成项目结构图，其他图跳过并 warning。

## 20. 执行顺序

1. 更新版本到 `0.7.0`。
2. 新增 diagram schema。
3. 更新 AgentState。
4. 实现 Mermaid 工具。
5. 新增 DiagramGenerateNode。
6. 更新 LangGraph。
7. 新增 diagram prompt 规范。
8. 更新 report_generate_node 保存 `diagrams.json`。
9. 更新 report_tool 新增“图示分析”章节。
10. 更新 analysis_service summary。
11. 新增/更新测试。
12. 更新 README。
13. 运行完整测试和示例验收。
14. 清理缓存和构建产物。
