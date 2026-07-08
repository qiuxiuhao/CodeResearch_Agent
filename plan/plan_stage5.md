# v0.5 开发计划：模型网络识别

## 1. 阶段目标

v0.5 基于 v0.4.1 已有的 AST 解析、文件级分析、函数级分析、`library_calls` 和全局库函数说明能力，新增深度学习模型网络结构识别能力：

- 识别继承 `nn.Module` / `torch.nn.Module` 的模型类。
- 判断项目中的模型主类候选。
- 解析模型类 `__init__` 中通过 `self.xxx = ...` 定义的网络层。
- 解析 `forward` 函数中的基础数据流。
- 识别 encoder / decoder / backbone / head / loss 等模块候选。
- 识别模型输入参数、返回表达式和基础输出说明。
- 输出 `model_analysis.json`。
- 在 `report.md` 中增加“模型网络结构分析”章节。
- 保持确定性静态分析，不调用 LLM，不引入外部文档检索。

## 2. 本阶段不做什么

v0.5 不做：

- 不实现论文解析。
- 不实现论文代码对齐。
- 不实现复杂模型图生成。
- 不生成 Mermaid / Graphviz / 可视化图。
- 不实现前端页面。
- 不实现前端零基础模式。
- 不实现 PDF 导出。
- 不引入复杂 RAG、向量数据库或官方文档检索。
- 不要求完全理解所有动态 `forward`、条件分支、循环或运行时 shape。
- 不做训练流程图、数据集流程图或项目全局调用图。

复杂图生成留到后续 v0.7。

## 3. 预计新增和修改的文件

新增文件：

```text
backend/app/schemas/model_analysis.py
backend/app/tools/model_detect_tool.py
backend/app/agents/nodes/model_analyze_node.py
backend/app/prompts/model_analyzer.md
tests/test_model_detect_tool.py
tests/test_model_analyze_node.py
plan/plan_stage5.md
```

修改文件：

```text
backend/app/schemas/state.py
backend/app/agents/graph.py
backend/app/agents/nodes/report_generate_node.py
backend/app/tools/report_tool.py
backend/app/services/analysis_service.py
backend/app/main.py
tests/test_langgraph_workflow.py
README.md
pyproject.toml
```

不修改：

```text
AGENTS.md
plan/plan_stage1.md
plan/plan_stage2.md
plan/plan_stage3.md
plan/plan_stage4.md
```

## 4. 每个文件的作用

- `schemas/model_analysis.py`：定义 `ModelAnalysis`、`ModelLayer`、`ForwardStep`、`ModelComponentCandidate` 等 Pydantic 模型。
- `tools/model_detect_tool.py`：提供可单测的确定性模型结构识别逻辑。
- `agents/nodes/model_analyze_node.py`：LangGraph 节点，读取 State 中的 `parsed_files`、`classes`、`functions`、`file_analysis`、`library_calls`、`function_analysis`，写入 `model_analysis`。
- `prompts/model_analyzer.md`：后续 LLM 模型分析 prompt 规范；v0.5 只作为规范，不调用 LLM。
- `report_generate_node.py`：保存 `model_analysis.json`，并把模型分析结果传给报告工具。
- `report_tool.py`：在 `report.md` 中增加“模型网络结构分析”章节。
- `analysis_service.py`：在 summary 中返回 `model_analysis_path`、`model_count`、`main_model_count`。
- `main.py`：FastAPI 版本同步到 `0.5.0`。
- `tests/test_model_detect_tool.py`：覆盖模型类、层识别、forward 数据流、组件候选等规则。
- `tests/test_model_analyze_node.py`：覆盖 LangGraph 节点 State 输入输出。
- `tests/test_langgraph_workflow.py`：覆盖完整 workflow 输出和报告章节。
- `README.md`、`pyproject.toml`：同步 v0.5.0 功能说明和版本号。

## 5. ModelAnalysis 数据结构设计

新增 `backend/app/schemas/model_analysis.py`，包含：

- `ModelLayer`：记录 `self.xxx` 层名、标准层类型、调用文本、行号、角色和证据。
- `ForwardStep`：记录 forward 中可识别语句的顺序、目标变量、表达式、调用函数、使用的模型层、行号和解释。
- `ModelComponentCandidate`：记录 encoder / decoder / backbone / head / loss 等候选模块。
- `ModelAnalysis`：记录模型类位置、基类、是否 `nn.Module`、是否主模型候选、输入输出、层、forward 步骤、组件候选、摘要、证据、警告和置信度。

输出 `model_analysis.json` 顶层结构：

```json
{
  "model_analysis": [],
  "errors": []
}
```

## 6. nn.Module 子类识别规则

基于 `classes[*].base_classes` 和文件 import alias 进行确定性识别。

高置信规则：

- base class 直接为 `nn.Module`。
- base class 直接为 `torch.nn.Module`。
- base class 经 alias 还原后为 `torch.nn.Module`。
- 文件中存在 `import torch.nn as nn` 且 base 为 `nn.Module`。

中置信规则：

- base class 名称以 `.Module` 结尾，且文件 import 中存在 `torch` 或 `torch.nn`。
- 类名或文件路径命中模型关键词，且类中同时存在 `__init__` 和 `forward`。

低置信规则：

- 仅路径或文件名像模型文件，但无法确认继承关系。

v0.5 只把高置信和中置信类纳入 `model_analysis`，低置信候选可记录到 `warnings`，不强行作为模型类输出。

## 7. 模型主类候选识别规则

在所有 `is_nn_module=True` 的类中打分，最高分标记 `is_main_model_candidate=True`。

评分：

- 继承确认是 `nn.Module`：+3。
- 类中存在 `forward`：+3。
- 类中存在 `__init__`：+2。
- `__init__` 中定义了至少一个 `self.xxx = nn.*` 或 `torch.nn.*` 层：+3。
- `forward` 中调用了 `self.xxx(...)`：+2。
- 文件级分析为 `model`：+2。
- 类名包含 `Model`、`Net`、`Network`、`Module`、`Classifier`、`EncoderDecoder`：+1。
- 类名包含 `Loss`：-2。
- 文件路径包含 `loss`：-2。

规则：

- 分数最高且分数 >= 6 的类为主模型候选。
- 多个并列时优先选择包含 `forward` 且层数量更多的类。
- 其他 `nn.Module` 类仍输出 `ModelAnalysis`，但 `is_main_model_candidate=False`。
- `main_model_reason` 必须写明得分证据。

## 8. `__init__` 网络层识别方案

只分析模型类的 `__init__` 函数源码。

识别对象：

- `self.layer = nn.Linear(...)`
- `self.layer = torch.nn.Linear(...)`
- `self.layer = nn.Sequential(...)`
- `self.layer = SomeModule(...)`
- `self.encoder = Encoder(...)`
- `self.backbone = build_backbone(...)`
- `self.loss_fn = nn.CrossEntropyLoss(...)`

实现方式：

- 使用 `ast.parse(function["source_code"])`。
- 遍历 `ast.Assign` 和 `ast.AnnAssign`。
- 目标必须是 `self.<name>`。
- 值为 `ast.Call` 时提取 `assigned_name`、`name`、`layer_type`、`call_text`、`line_no`。
- 使用 import alias 将 `nn.Linear` 等常见类型标准化为 `torch.nn.Linear`。

层角色初步判断：

- 名称或类型包含 `encoder` -> `encoder`
- 名称或类型包含 `decoder` -> `decoder`
- 名称或类型包含 `backbone`、`resnet`、`vit`、`transformer` -> `backbone`
- 名称或类型包含 `head` -> `head`
- 名称或类型包含 `classifier`、`fc`、`linear` -> `classifier`
- 名称或类型包含 `loss`、`criterion` -> `loss`
- 类型包含 `BatchNorm`、`LayerNorm` -> `normalization`
- 类型包含 `ReLU`、`GELU`、`Sigmoid`、`Softmax` -> `activation`
- 无法判断则 `unknown`

## 9. `forward` 数据流基础识别方案

只分析模型类的 `forward` 函数源码。

识别范围：

- 顺序语句中的赋值，例如 `x = self.layer(x)`。
- 返回语句，例如 `return logits` 或 `return logits, loss`。
- 表达式调用，例如 `x = F.relu(x)` 或 `x = torch.cat([...], dim=1)`。

实现方式：

- 使用 AST 遍历 `forward` 函数 body 的顶层语句。
- 对 `Assign`、`AnnAssign`、`Expr`、`Return` 生成 `ForwardStep`。
- `target` 为赋值目标文本；`Return` 的 target 为 `None`。
- `expression` 为右侧表达式或 return 表达式文本。
- `calls` 收集当前表达式内的 call func 文本。
- `uses_layers` 收集 `self.xxx(...)` 且 `xxx` 出现在 `layers.name` 中的调用。
- 对 `if`、`for`、`while` 内部做浅层提取，并在 `warnings` 记录限制。

## 10. encoder / decoder / backbone / head / loss 候选识别规则

候选来源：

- `__init__` 中的层赋值。
- 模型类名。
- 函数名。
- 文件路径。
- `forward` 中调用的 `self.xxx(...)`。
- `library_calls` 中常见 loss 或 head 相关调用。

关键词规则：

- encoder：`encoder`、`enc`
- decoder：`decoder`、`dec`
- backbone：`backbone`、`resnet`、`vgg`、`vit`、`transformer`、`feature_extractor`
- head：`head`、`cls_head`、`bbox_head`、`seg_head`、`projection`
- classifier：`classifier`、`fc`、`linear`
- loss：`loss`、`criterion`、`CrossEntropyLoss`、`MSELoss`、`BCEWithLogitsLoss`
- embedding：`embedding`、`embed`
- normalization：`norm`、`BatchNorm`、`LayerNorm`
- activation：`relu`、`gelu`、`sigmoid`、`softmax`

置信度：

- 名称和层类型同时命中：`high`
- 名称或层类型单独命中：`medium`
- 仅路径或上下文命中：`low`

输出时只把 `medium` 和 `high` 候选放入 `component_candidates`；`low` 候选进入 `warnings`。

## 11. 模型输入输出识别规则

输入识别：

- 从 `forward` 函数参数读取。
- 排除 `self`。
- 保留参数顺序。

输出识别：

- 从 `forward` 中的 `Return` 节点提取表达式文本。
- 支持单变量、tuple/list、dict、调用表达式。
- 如果没有显式 return，输出 `["无显式 return"]`，并在 `warnings` 记录。
- 不推断真实 Tensor shape；只根据表达式和层调用给出基础说明。

## 12. ModelAnalyzeNode 设计

节点名：

```text
model_analyze
```

节点位置：

```text
library_call_extract -> function_analyze -> model_analyze -> library_function_doc -> report_generate
```

输入 State：

```text
parsed_files
classes
functions
file_analysis
library_calls
function_analysis
errors
```

输出 State：

```text
model_analysis
errors
```

节点行为：

- 调用 `detect_models(...)`。
- 将 Pydantic 结果转为 dict 写入 `state["model_analysis"]`。
- 如果没有模型类，写入空列表，不报错。
- 单个类解析失败不应中断整个 workflow。

## 13. model_detect_tool 设计

新增 `backend/app/tools/model_detect_tool.py`。

核心函数：

```python
def detect_models(
    parsed_files: list[dict],
    classes: list[dict],
    functions: list[dict],
    file_analysis: list[dict],
    library_calls: list[dict],
    function_analysis: list[dict],
) -> list[ModelAnalysis]:
    ...
```

实现约束：

- 只使用 Python 标准库 `ast` 和现有 schema。
- 不引入深度学习框架运行时依赖。
- 不 import 用户项目代码。
- 不执行 ZIP 中的任何代码。
- 所有结论必须写入 `evidence` 或 `warnings`。
- 遇到语法片段解析失败时返回部分结果，并记录 warning。

## 14. model_analyzer prompt 设计

新增 `backend/app/prompts/model_analyzer.md`，说明角色、输入、输出 JSON 格式、禁止事项和 v0.5 不调用 LLM 的约束。

## 15. 输出文件设计

新增输出：

```text
outputs/{task_id}/model_analysis.json
```

结构：

```json
{
  "model_analysis": [],
  "errors": []
}
```

新增 State 字段：

```python
model_analysis: list[dict]
```

更新 summary：

```json
{
  "model_analysis_path": ".../model_analysis.json",
  "model_count": 1,
  "main_model_count": 1
}
```

## 16. report.md 更新方式

在“逐函数分析”之后、“Python 库函数说明”之前新增：

```markdown
## 模型网络结构分析
```

报告只展示当前任务识别出的模型类、模型层、forward 主要流程、模块候选和静态识别注意事项。不展示源码全文，不生成 Mermaid 或复杂图。

## 17. 测试计划

新增 `tests/test_model_detect_tool.py`：

- 识别 `class SimpleNet(nn.Module)` 为 `is_nn_module=True`。
- 识别含 `__init__` 和 `forward` 的类为主模型候选。
- 从 `__init__` 中识别 `self.fc1 = nn.Linear(...)`、`self.fc2 = nn.Linear(...)`。
- 从 `forward` 中识别 `self.fc1(x)`、`F.relu(...)`、`self.fc2(...)` 的顺序步骤。
- 识别 forward 输入 `x`。
- 识别 return 输出表达式。
- 识别 classifier/head 候选。
- 对非 `nn.Module` 类不输出 `ModelAnalysis`。
- 对包含分支或循环的 forward 记录 warning，但不中断。

新增 `tests/test_model_analyze_node.py`：

- 给定最小 State，节点写入 `model_analysis`。
- 空类列表或无模型类时输出空 `model_analysis`。
- 节点保留原 State 中其他字段。

修改 `tests/test_langgraph_workflow.py`：

- 完整 workflow 输出 `model_analysis.json`。
- `model_analysis.json.model_analysis` 至少包含 `SimpleNet`。
- `SimpleNet.is_main_model_candidate=True`。
- `SimpleNet.layers` 包含 `fc1` 和 `fc2`。
- `SimpleNet.forward_steps` 非空。
- `report.md` 包含“模型网络结构分析”章节。

## 18. 验收标准

- 版本号更新为 `0.5.0`。
- 新增 `model_analysis.json`。
- `AgentState` 包含 `model_analysis`。
- LangGraph 中包含 `model_analyze` 节点。
- 示例项目中 `SimpleNet` 被识别为 `nn.Module`。
- 示例项目中 `SimpleNet` 被识别为主模型候选。
- 示例项目中 `self.fc1`、`self.fc2` 被识别为网络层。
- 示例项目中 `forward` 的主要数据流被识别。
- `report.md` 包含“模型网络结构分析”章节。
- 原有输出继续保留。
- `pytest -q` 全部通过。
- 不实现论文解析、论文代码对齐、复杂模型图、前端页面、PDF 导出或 RAG。

## 19. 可能风险和解决方案

风险：复杂动态 forward 无法完全识别。  
解决方案：v0.5 明确只做基础静态顺序识别；对分支、循环、动态 getattr 等记录 `warnings`。

风险：误把普通类识别为模型类。  
解决方案：优先依赖继承关系；仅路径或类名命中不进入正式 `model_analysis`。

风险：主模型候选误判。  
解决方案：使用可解释打分，并在 `main_model_reason` 和 `evidence` 中记录依据；多个模型类全部输出。

风险：层类型 alias 还原不完整。  
解决方案：先支持 `nn.*`、`torch.nn.*`、项目内部 Module 构造和常见 builder 函数；无法标准化时保留原始 `layer_type`。

风险：输出过长。  
解决方案：报告中只展示模型层、forward 主要步骤和候选模块；完整细节放入 `model_analysis.json`。

风险：和 v0.4 library docs 顺序冲突。  
解决方案：`model_analyze` 插入在 `function_analyze` 后、`library_function_doc` 前，只读 `library_calls`，不修改库函数入库状态。

## 20. 执行顺序

1. 更新版本到 `0.5.0`。
2. 新增 `backend/app/schemas/model_analysis.py`。
3. 更新 `AgentState`，增加 `model_analysis`。
4. 实现 `backend/app/tools/model_detect_tool.py`。
5. 新增 `backend/app/agents/nodes/model_analyze_node.py`。
6. 更新 LangGraph，将 `model_analyze` 插入 `function_analyze` 和 `library_function_doc` 之间。
7. 新增 `backend/app/prompts/model_analyzer.md`。
8. 更新 `report_generate_node.py`，保存 `model_analysis.json`。
9. 更新 `report_tool.py`，增加“模型网络结构分析”章节。
10. 更新 `analysis_service.py` summary。
11. 新增和更新测试。
12. 更新 README。
13. 运行 `conda run -n code-research-agent pytest -q`。
14. 运行示例 ZIP 验收。
15. 清理缓存和构建产物。
