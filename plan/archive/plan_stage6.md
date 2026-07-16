# v0.6 开发计划：论文解析与论文代码对齐 MVP

## 1. 阶段目标

v0.6 基于 v0.5.1 已有的代码仓库分析、函数分析、库函数识别、全局库函数说明和模型网络识别能力，新增“可选论文 PDF”分析能力：

- 支持 CLI / API / `run_analysis()` 传入可选 `paper_pdf_path`。
- 使用 PyMuPDF 提取论文 PDF 文本和基础分页信息。
- 提取论文标题、摘要、方法相关文本、核心创新点、关键模块名和关键词。
- 将论文创新点与代码中的文件、类、函数、模型模块进行启发式对齐。
- 输出 `paper_analysis.json` 和 `paper_code_alignment.json`。
- 在 `report.md` 中增加“论文解析与论文代码对齐”章节。
- 没有上传论文时，代码分析流程仍正常完成，并输出空的论文分析结构。
- 所有对齐结果必须包含置信度；无法确认的关系标记为 `low` 或 `unmatched`。
- v0.6 只做 MVP，不做复杂 RAG、公式解析、图生成增强、前端或 PDF 报告导出。

## 2. 本阶段不做什么

v0.6 不做：

- 不实现复杂 RAG、向量数据库、embedding 检索或跨文档问答。
- 不实现复杂论文公式解析、图表理解、表格结构化或图片 OCR。
- 不实现论文图与代码图对齐。
- 不实现复杂模型图生成、Mermaid 增强或 Graphviz。
- 不实现前端页面、文件上传 UI 或零基础模式。
- 不实现 PDF 报告导出。
- 不强行把所有论文创新点都对齐到代码。
- 不调用外部 LLM；prompt 文件仅作为后续扩展规范。
- 不执行用户代码，不 import 用户项目。

## 3. 预计新增和修改的文件

新增文件：

```text
backend/app/schemas/paper.py
backend/app/tools/paper_parse_tool.py
backend/app/tools/paper_code_align_tool.py
backend/app/agents/nodes/paper_analyze_node.py
backend/app/agents/nodes/paper_code_align_node.py
backend/app/prompts/paper_analyzer.md
backend/app/prompts/paper_code_aligner.md
tests/test_paper_parse_tool.py
tests/test_paper_code_align_tool.py
tests/test_paper_nodes.py
plan/plan_stage6.md
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
plan/plan_stage5.md
```

## 4. 每个文件的作用

- `schemas/paper.py`：定义 `PaperAnalysis`、`PaperContribution`、`PaperCodeAlignment`、`PaperCodeAlignmentItem`、`PaperKeyword` 等 Pydantic 模型。
- `tools/paper_parse_tool.py`：使用 PyMuPDF 读取 PDF 文本，做确定性章节抽取、关键词抽取、创新点候选提取。
- `tools/paper_code_align_tool.py`：将论文创新点和关键词与 `repo_index`、`file_analysis`、`function_analysis`、`model_analysis` 等结构化代码结果做启发式匹配。
- `agents/nodes/paper_analyze_node.py`：读取可选 `paper_pdf_path`，输出 `paper_analysis`。
- `agents/nodes/paper_code_align_node.py`：读取 `paper_analysis` 和代码分析结果，输出 `paper_code_alignment`。
- `prompts/paper_analyzer.md`、`prompts/paper_code_aligner.md`：后续 LLM prompt 规范；v0.6 不调用。
- `report_generate_node.py`：保存 `paper_analysis.json`、`paper_code_alignment.json`，并传入报告工具。
- `report_tool.py`：新增“论文解析与论文代码对齐”章节。
- `analysis_service.py`：支持 `paper_pdf_path` 参数和 CLI `--paper-pdf-path`，summary 返回论文输出路径和统计。
- `main.py`：FastAPI request model 增加 `paper_pdf_path`，版本更新为 `0.6.0`。
- `pyproject.toml`：版本更新为 `0.6.0`，新增 `pymupdf` 依赖。

## 5. PaperAnalysis 数据结构设计

`PaperAnalysis` 包含：

- `paper_provided`
- `paper_path`
- `title`
- `abstract`
- `method_text`
- `sections`
- `contributions`
- `keywords`
- `module_names`
- `raw_text_char_count`
- `page_count`
- `warnings`
- `errors`
- `confidence`

无论文时输出 `paper_provided=false`、空 contributions/keywords/module_names，并记录 warning。

## 6. PaperContribution 数据结构设计

`PaperContribution` 包含：

- `id`
- `title`
- `description`
- `source_section`
- `page_no`
- `keywords`
- `evidence`
- `confidence`

每条创新点必须来自论文句子证据，最多输出 5 条。

## 7. PaperCodeAlignment 数据结构设计

对齐模型包含：

- `PaperCodeTarget`
- `PaperCodeAlignmentItem`
- `PaperCodeAlignment`

每条 alignment item 必须包含 `status`、`confidence`、`reason`、`evidence`。无法确认时标记 `unmatched`。

## 8. PDF 解析方案

- 使用 PyMuPDF 的 `fitz.open()`。
- 逐页调用 `page.get_text("text")`。
- 保存页数、原始字符数和路径。
- 路径不存在、PDF 打不开、空文本时记录 error/warning，不中断 workflow。
- 不做 OCR、公式解析、表格解析、图片解析或版面重建。

## 9. 论文核心创新点提取方案

从 Abstract、Introduction、Contributions、Method、Approach、Architecture 等章节中按句子抽取候选。命中 `we propose`、`we introduce`、`novel`、`framework`、`module`、`architecture`、`loss`、`encoder`、`decoder`、`head` 等模式时生成 contribution，并附 evidence 和 confidence。

## 10. 论文关键词和模块名提取方案

关键词来自标题、摘要、方法文本、贡献句和高频词。模块名来自 CamelCase 名称以及 `Module`、`Net`、`Encoder`、`Decoder`、`Backbone`、`Head`、`Loss` 等模式。结果去重并限制数量。

## 11. 论文-代码对齐规则

对齐使用启发式分数：

- 精确名称匹配：高权重。
- snake_case / CamelCase 分词交集：中权重。
- encoder/head/loss 等角色匹配：中权重。
- 文件类型、函数名、模型模块、库调用与贡献关键词匹配：中低权重。
- 仅通用词不计分。

每个 contribution 最多保留 5 个匹配目标，低于阈值标记 `unmatched`。

## 12. 对齐置信度设计

- `high`：精确名称匹配且有多个证据来源。
- `medium`：关键词重叠和结构角色匹配，但无精确名称。
- `low`：只有弱关键词或路径级相关。
- `unmatched`：无可靠对应关系。

## 13. PaperAnalyzeNode 设计

节点名：

```text
paper_analyze
```

节点位置：

```text
model_analyze -> paper_analyze -> paper_code_align -> library_function_doc -> report_generate
```

无 `paper_pdf_path` 时输出空 `paper_analysis`，不新增全局 error。有 PDF 时调用 `parse_paper_pdf()`。

## 14. PaperCodeAlignNode 设计

节点名：

```text
paper_code_align
```

有论文时调用 `align_paper_to_code()`；无论文时输出空 alignment。

## 15. paper_parse_tool 设计

核心函数：

```python
def parse_paper_pdf(paper_pdf_path: str | Path) -> PaperAnalysis:
    ...
```

内部包含 PDF 页提取、标题抽取、章节识别、摘要抽取、方法文本抽取、创新点抽取、关键词抽取和模块名抽取。

## 16. paper_code_align_tool 设计

核心函数：

```python
def align_paper_to_code(
    paper_analysis: dict,
    repo_index: dict,
    file_analysis: list[dict],
    classes: list[dict],
    functions: list[dict],
    function_analysis: list[dict],
    model_analysis: list[dict],
    library_calls: list[dict],
) -> PaperCodeAlignment:
    ...
```

代码目标类型为 `file`、`class`、`function`、`model_module`。

## 17. paper_analyzer prompt 设计

新增 `paper_analyzer.md`，定义后续 LLM 论文解析输入输出、禁止编造、禁止解析公式图表、v0.6 不调用 LLM。

## 18. paper_code_aligner prompt 设计

新增 `paper_code_aligner.md`，定义后续 LLM 对齐输入输出、禁止强行匹配、必须输出证据和置信度、v0.6 不调用 LLM。

## 19. 输出文件设计

新增：

```text
outputs/{task_id}/paper_analysis.json
outputs/{task_id}/paper_code_alignment.json
```

无论文时也输出空结构，保证输出稳定。

## 20. report.md 更新方式

在“模型网络结构分析”之后、“Python 库函数说明”之前新增：

```markdown
## 论文解析与论文代码对齐
```

报告展示标题、摘要预览、创新点、关键词、模块名、对齐结果、未匹配项和 v0.6 启发式说明。

## 21. API / CLI 如何支持可选论文 PDF

`run_analysis()` 新增 `paper_pdf_path` 参数；CLI 新增 `--paper-pdf-path`；FastAPI `AnalysisTaskRequest` 新增 `paper_pdf_path`。不传时保持 v0.5.1 行为。

## 22. 测试计划

- `test_paper_parse_tool.py`：用 PyMuPDF 生成临时 PDF，测试 title/abstract/method/contribution/keyword/module 提取和错误处理。
- `test_paper_code_align_tool.py`：测试 matched/unmatched、confidence 和 target evidence。
- `test_paper_nodes.py`：测试无论文、有论文和节点 State 保留。
- 更新 API request model 测试。
- 更新 workflow 测试：无论文仍通过，有论文输出非空论文 JSON 和报告章节。

## 23. 验收标准

- 版本号为 `0.6.0`。
- 新增 PyMuPDF 依赖。
- CLI/API 支持可选 `paper_pdf_path`。
- 无论文时完整代码分析仍成功。
- 输出 `paper_analysis.json` 和 `paper_code_alignment.json`。
- 有测试 PDF 时能提取标题、摘要、方法文本、创新点和关键词。
- 对齐结果包含 status 和 confidence。
- 不确定关系标记为 low 或 unmatched。
- `report.md` 包含“论文解析与论文代码对齐”章节。
- `pytest -q` 全部通过。

## 24. 可能风险和解决方案

- 扫描版 PDF 无文本：记录 warning，不中断，OCR 留后续。
- 章节标题不标准：使用多种标题 alias 和全文 fallback。
- 创新点提取不准确：所有结果带 evidence 和 confidence。
- 对齐误匹配：低分标 unmatched，不强行匹配。
- 报告过长：报告只展示摘要预览和最多 5 条贡献，完整结果放 JSON。
- PyMuPDF 环境影响：只新增明确依赖，测试生成临时 PDF，不提交二进制。

## 25. 执行顺序

1. 更新版本和 PyMuPDF 依赖。
2. 新增 paper schema。
3. 实现 PDF 解析工具。
4. 实现论文-代码对齐工具。
5. 新增 paper LangGraph 节点。
6. 更新 State 和 LangGraph。
7. 更新 CLI/API。
8. 新增 prompt 规范。
9. 更新报告输出和 Markdown 章节。
10. 新增/更新测试。
11. 更新 README。
12. 运行测试和无论文/有论文验收。
13. 清理缓存和构建产物。
