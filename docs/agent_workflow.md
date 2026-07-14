# Agent 工作流

分析流程由 LangGraph 管理。各节点共享同一个状态对象，并把确定性的结构化产物写入当前任务的输出目录。

## 节点顺序

```text
unzip
repo_scan
code_parse
file_analyze
library_call_extract
function_analyze
model_analyze
paper_analyze
paper_figure_extract
paper_code_align
file_explain_llm
function_explain_llm
model_explain_llm
paper_figure_analyze_vlm
paper_code_align_llm
diagram_generate
teaching_diagram_plan
teaching_diagram_generate
teaching_diagram_review_vlm
library_function_doc
report_generate
```

## 节点职责

- `unzip`：安全解压输入 ZIP 到当前任务的 source 目录。
- `repo_scan`：扫描 Python 文件，并识别入口、模型、训练、推理、配置等候选文件。
- `code_parse`：基于 Python AST 提取 import、alias、类、函数、方法和行号范围。
- `file_analyze`：生成确定性的文件级用途和项目位置分析。
- `library_call_extract`：识别 Python / PyTorch / NumPy / PIL / OpenCV / einops 风格的库函数调用。
- `function_analyze`：总结函数用途、输入、输出、实现逻辑和库函数调用。
- `model_analyze`：识别 `nn.Module` 风格的模型类、网络层、forward 流程和模块候选。
- `paper_analyze`：可选解析本地论文 PDF，提取标题、摘要、贡献点、关键词和模块名。
- `paper_figure_extract`：本地提取 Figure caption、页码、bbox、引用次数、原始资产和 canonical preview。
- `paper_code_align`：把论文贡献点对齐到文件、类、函数和模型模块，并标注置信度。
- 三个普通 `*_llm` 节点：仅在文本 LLM 开关和文本 consent 通过时生成独立教学解释。
- `paper_figure_analyze_vlm`：在图片 consent 通过后分析筛选 Figure，不读取整个 PDF，也不生成代码目标。
- `paper_code_align_llm`：在文本 LLM 开启时读取规则对齐和可用 FigureAnalysis，并仅从代码 evidence catalog 生成建议关联。
- `diagram_generate`：基于已有结构化结果生成 Mermaid 源码图。
- `teaching_diagram_plan`：读取规则事实和 `diagrams.json`，本地生成教学图 Skeleton/Spec；文案可扩展为 DeepSeek/Qwen，但不得改变模块、连接、Shape 或公式。
- `teaching_diagram_generate`：先生成本地 Blueprint SVG/PNG，再在独立图片授权通过时尝试生成 AI raw 图并由本地 Compositor 合成。
- `teaching_diagram_review_vlm`：在独立视觉授权通过时审查 `styled_composite.png`，不合格则回退 Blueprint。
- `library_function_doc`：把教学级库函数说明写入 SQLite，并复用已有说明。
- `report_generate`：保存最终 JSON 产物并生成 `report.md`。

## 设计原则

- 优先使用确定性的静态分析。
- 不执行用户项目代码。
- 分析流程中不做网络检索。
- 重要结论尽量带 evidence 和 confidence。
- 论文 PDF 等可选输入缺失时，输出空结构，不影响代码分析主流程。
- 默认纯规则模式零外部调用；文本、论文视觉、教学图图片生成和教学图审查具有独立 consent、预算、缓存和 retry/fallback 计数。
