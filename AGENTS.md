# AGENTS.md

# CodeResearch Agent 项目开发总指导

## 1. 项目定位

本项目名为 **CodeResearch Agent**。

这是一个面向深度学习代码仓库和论文的智能分析系统。用户可以上传一个代码 ZIP 压缩包，并可选上传对应论文 PDF。系统需要自动完成代码仓库解析、逐文件分析、逐函数分析、模型网络结构识别、Python / PyTorch 库函数识别、全局函数知识库沉淀、论文核心创新点提取、论文与代码对齐、模型图生成和技术报告导出。

本项目不是普通聊天机器人，也不是简单的代码问答工具，而是一个面向真实工程场景的 **代码仓库理解 Agent 系统**。

项目完成后应同时满足两个目标：

1. **日常学习目标**：帮助用户高效阅读深度学习开源项目，理解代码结构、函数逻辑、模型网络、库函数作用和论文创新点。
2. **求职简历目标**：项目整体设计、代码结构、技术选型和工程实现要尽可能贴近真实公司项目水平，体现 Agent 开发、工具调用、代码静态分析、RAG、知识库沉淀、图生成、报告生成和系统工程能力。

因此，开发过程中不能只追求“能跑”，还要重视架构清晰、模块解耦、可维护、可扩展、可测试、可展示。

---

## 2. 项目核心能力

本项目最终应具备以下核心能力：

1. 上传代码 ZIP 并自动解压。
2. 扫描项目目录结构。
3. 识别 Python 文件、入口文件、模型文件、训练文件、推理文件、数据集文件、配置文件。
4. 使用 AST / tree-sitter 解析代码结构。
5. 抽取每个文件中的 import、class、function、line range、调用关系。
6. 逐个文件分析其作用和在项目中的位置。
7. 逐个函数分析其功能、输入、输出、实现逻辑、计算逻辑和模型位置。
8. 识别函数内部调用的 Python / PyTorch / NumPy / OpenCV 等库函数。
9. 维护一个全局可复用的 Python 函数库知识库。
10. 支持正常模式和零基础模式。
11. 在零基础模式下，显示当前函数调用的库函数，并支持点击弹窗查看教学级解释。
12. 识别 PyTorch 模型结构，例如 `nn.Module`、`__init__`、`forward`、encoder、decoder、loss。
13. 如果上传论文 PDF，则解析论文并提取核心创新点。
14. 将论文核心创新点与代码文件、类、函数进行对齐。
15. 生成项目结构图、模型流程图、核心模块图、函数逻辑图。
16. 生成 Markdown / HTML / PDF 技术报告。
17. 支持历史任务查看和结果复用。

---

## 3. 核心技术路线

本项目采用：

**LangGraph + 自定义工具链 + 代码静态分析 + 全局函数知识库 + 论文解析 + RAG + 图生成 + 报告导出**

推荐技术栈如下：

- 后端框架：FastAPI
- Agent 编排：LangGraph
- 代码解析：Python `ast`，后续可扩展 `tree-sitter`
- 数据模型：Pydantic
- 数据库：SQLite 起步，后续可扩展 PostgreSQL
- 全局函数知识库：SQLite / PostgreSQL
- 论文解析：PyMuPDF，后续可扩展 GROBID / LlamaParse / MinerU
- 向量检索：Chroma 起步，后续可扩展 Qdrant / pgvector
- 图生成：Mermaid 起步，后续可扩展 Graphviz
- 报告生成：Markdown 起步，后续扩展为 LaTeX / PDF
- 前端：React / Next.js
- 任务队列：MVP 阶段可先同步执行，后续扩展 Celery / RQ
- 测试框架：pytest

---

## 4. 总体设计原则

### 4.1 不要做成一个大 Prompt

禁止把整个 ZIP 解压后的代码一次性塞给大模型分析。

正确做法是：

1. 先用确定性的程序解析代码结构。
2. 再用 Agent 对结构化结果进行解释。
3. 最后汇总成项目级分析报告。

整体流程应该是：

```text
代码结构解析
  ↓
库函数调用识别
  ↓
函数级分析
  ↓
文件级分析
  ↓
模型结构识别
  ↓
论文解析与论文代码对齐
  ↓
图生成
  ↓
报告导出
```

---

### 4.2 Agent 必须有工具，而不是只会聊天

本项目中的 Agent 必须通过自定义工具完成真实任务，例如：

- 解压 ZIP
- 扫描项目目录
- 解析 Python 文件
- 提取 import / class / function
- 识别函数内部库函数调用
- 查询和更新全局 Python 函数知识库
- 识别 `nn.Module`
- 识别 `forward` 函数
- 构建调用关系
- 解析论文 PDF
- 提取论文创新点
- 生成 Mermaid 图
- 生成 Markdown 报告

不能只写一个普通对话接口。

---

### 4.3 每个阶段都要有结构化产物

每个阶段都必须输出结构化文件，便于调试、复用和展示。

推荐中间产物包括：

```text
repo_index.json
parsed_files.json
library_calls.json
library_function_docs.json
file_analysis.json
function_analysis.json
model_analysis.json
paper_analysis.json
paper_code_alignment.json
diagrams.json
report.md
```

这些文件应存放在某个分析任务的独立输出目录中，例如：

```text
outputs/{task_id}/
```

---

### 4.4 结果必须可追溯

系统生成的解释不能完全凭空总结。重要结论要尽量能追溯到：

- 文件路径
- 类名
- 函数名
- 代码行号
- 调用关系
- 库函数名
- 论文章节
- 论文关键词

例如：

某个函数被判断为模型核心函数时，应该说明它来自哪个文件、哪个类、哪个函数，以及为什么重要。

某个库函数被解释为 PyTorch 函数时，应该说明其标准函数名、原始调用方式、所在行号和置信度。

---

### 4.5 允许分阶段实现，不允许一次性堆功能

本项目必须按版本逐步开发。每个版本都要能独立运行、独立测试、独立验收。

不要在 v0.1 阶段就同时实现论文解析、模型图、前端、全局知识库和 PDF 导出。应该先把最小闭环跑通。

---

## 5. 推荐项目目录结构

项目根目录建议如下：

```text
code-research-agent/
  AGENTS.md
  README.md
  pyproject.toml
  .env.example
  .gitignore

  backend/
    app/
      main.py

      api/
        routes_analysis.py
        routes_library.py

      agents/
        graph.py
        nodes/
          unzip_node.py
          repo_scan_node.py
          code_parse_node.py
          library_call_extract_node.py
          library_function_doc_node.py
          function_analyze_node.py
          file_analyze_node.py
          model_analyze_node.py
          paper_analyze_node.py
          paper_code_align_node.py
          diagram_generate_node.py
          report_generate_node.py

      tools/
        unzip_tool.py
        repo_scan_tool.py
        ast_parse_tool.py
        library_call_extractor_tool.py
        library_function_resolver_tool.py
        library_doc_lookup_tool.py
        model_detect_tool.py
        paper_parse_tool.py
        mermaid_tool.py
        report_tool.py

      services/
        storage_service.py
        analysis_service.py
        library_function_service.py

      schemas/
        state.py
        repo.py
        code.py
        library_function.py
        paper.py
        diagram.py
        report.py

      prompts/
        function_analyzer.md
        file_analyzer.md
        model_analyzer.md
        library_function_doc_writer.md
        paper_analyzer.md
        paper_code_aligner.md
        report_writer.md

      utils/
        path_utils.py
        file_utils.py
        json_utils.py

  frontend/
    src/
      pages/
      components/
      services/

  docs/
    requirement.md
    architecture.md
    agent_workflow.md
    api.md
    database.md
    development_plan.md

  tests/
    test_repo_scan.py
    test_ast_parse.py
    test_library_call_extract.py
    test_library_function_service.py
    test_langgraph_workflow.py

  examples/
    small_pytorch_project.zip

  outputs/
```

MVP 阶段可以暂时不实现完整前端，但后端结构、工具链和 Agent 工作流要先设计清楚。

---

## 6. LangGraph 工作流设计

本项目的 LangGraph 工作流建议如下：

```text
START
  ↓
UnzipNode
  ↓
RepoScanNode
  ↓
CodeParseNode
  ↓
LibraryCallExtractNode
  ↓
LibraryFunctionDocNode
  ↓
FunctionAnalyzeNode
  ↓
FileAnalyzeNode
  ↓
ModelAnalyzeNode
  ↓
PaperCheckNode
  ↓
如果有论文：
    PaperAnalyzeNode
      ↓
    PaperCodeAlignNode
  ↓
DiagramGenerateNode
  ↓
ReportGenerateNode
  ↓
END
```

---

## 7. LangGraph 节点职责

### 7.1 UnzipNode

负责解压用户上传的 ZIP 文件，并创建独立任务目录。

输出：

- 解压后的项目路径
- 原始 ZIP 文件路径
- 任务 ID
- 输出目录

---

### 7.2 RepoScanNode

负责扫描项目目录。

输出：

- 文件树
- Python 文件列表
- 可能的入口文件
- 可能的模型文件
- 可能的训练文件
- 可能的推理文件
- 可能的数据集文件
- 可能的配置文件
- 需要跳过的无关文件

---

### 7.3 CodeParseNode

负责使用 `ast` 解析 Python 文件。

输出：

- 每个文件的 import
- import alias 映射
- 每个文件的 class
- 每个文件的 function
- 每个函数的参数
- 每个函数的起止行号
- 每个函数的源码片段
- 每个类的继承关系
- 每个函数的原始调用表达式

---

### 7.4 LibraryCallExtractNode

负责识别每个函数内部调用的 Python 库函数。

输入：

- parsed_files
- functions
- imports
- aliases
- function source code

输出：

- 每个函数的 `library_calls`
- 标准函数名
- 原始调用文本
- 所在行号
- 所属包
- 类别
- 置信度

重点要求：

1. 尽量识别 PyTorch、NumPy、OpenCV、PIL、einops、Python 标准库等函数。
2. 要处理 import alias。
3. 不要把项目内部函数误判为外部库函数。
4. 不确定时标记为低置信度。

---

### 7.5 LibraryFunctionDocNode

负责检查库函数是否已经存在于全局 Python 函数知识库。

流程：

```text
读取当前项目识别出的 library_calls
  ↓
按 canonical_name 去全局知识库查询
  ↓
如果已存在：
    直接复用
如果不存在：
    生成或检索教学级解释
    写入全局知识库
  ↓
记录该库函数在当前项目中的出现位置
```

输出：

- 当前任务涉及的库函数解释
- 新增入库的库函数
- 函数出现记录
- 低置信度待确认列表

---

### 7.6 FunctionAnalyzeNode

负责逐个函数分析。

输出：

- 函数作用
- 输入说明
- 输出说明
- 实现逻辑
- 计算逻辑
- 调用关系
- 是否属于核心代码
- 是否可能与模型网络有关
- 当前函数调用的库函数列表
- 通俗解释

---

### 7.7 FileAnalyzeNode

负责逐个文件分析。

输出：

- 文件作用
- 文件在项目中的位置
- 文件和其他文件的关系
- 文件内部主要类和函数
- 是否是核心模型文件
- 是否是训练、推理、数据、配置或工具文件

---

### 7.8 ModelAnalyzeNode

负责识别深度学习模型结构。

重点识别：

- `nn.Module`
- `__init__`
- `forward`
- encoder
- decoder
- backbone
- head
- loss
- dataloader
- train loop
- inference loop

输出：

- 模型主类
- 模型输入输出
- 网络主流程
- 核心模块列表
- 模型结构草图数据
- 关键 forward 路径

---

### 7.9 PaperAnalyzeNode

如果用户上传论文 PDF，则负责论文解析。

输出：

- 论文标题
- 摘要总结
- 方法部分总结
- 核心创新点
- 关键模块名
- 关键公式
- 论文中的模型流程
- 论文中的实验任务

---

### 7.10 PaperCodeAlignNode

负责论文创新点和代码实现的对齐。

输出：

- 每个论文创新点对应的代码文件
- 每个论文创新点对应的类和函数
- 对齐依据
- 对齐置信度
- 可能不确定的地方

不要强行对齐。如果没有足够证据，应标记为“未确认”或“低置信度”。

---

### 7.11 DiagramGenerateNode

负责生成模型图、代码结构图和论文代码对齐图。

优先输出 Mermaid 代码。

推荐图类型：

- 项目结构图
- 模型整体流程图
- 核心模块图
- 函数计算流程图
- 论文创新点到代码实现的对应图

要求：

1. 图中节点应尽量来自真实代码结构或论文模块。
2. 不要凭空画代码中不存在的模块。
3. 图要适合初学者理解。
4. 图可以直接放入报告。

---

### 7.12 ReportGenerateNode

负责生成最终 Markdown 报告。

报告必须适合初学者阅读，也要适合放进项目展示。

报告结构建议：

1. 项目总览
2. 目录结构说明
3. 运行入口分析
4. 核心模型结构
5. 文件级分析
6. 函数级分析
7. 当前项目涉及的 Python / PyTorch 库函数
8. 论文创新点对齐
9. 模型图与流程图
10. 核心代码通俗解释
11. 学习建议
12. 项目分析结论

---

## 8. AgentState 设计

LangGraph 中的 State 是整个项目的核心。所有节点都应围绕统一 State 读写数据。

推荐初始版本：

```python
from typing import TypedDict, Optional

class AgentState(TypedDict, total=False):
    task_id: str

    zip_path: str
    repo_path: str
    paper_path: Optional[str]

    output_dir: str

    file_tree: dict
    python_files: list[str]

    repo_index: dict
    parsed_files: list[dict]
    functions: list[dict]
    classes: list[dict]

    library_calls: list[dict]
    library_function_docs: list[dict]
    new_library_functions: list[dict]
    low_confidence_library_calls: list[dict]

    file_analysis: list[dict]
    function_analysis: list[dict]
    model_analysis: dict

    paper_analysis: Optional[dict]
    paper_code_alignment: Optional[list[dict]]

    diagrams: list[dict]
    report_md: str

    errors: list[dict]
```

开发要求：

1. 每个节点只更新自己负责的字段。
2. 不要在节点之间传递零散变量，统一通过 State。
3. 所有关键 State 内容都要能保存为 JSON 文件。
4. 遇到错误时，不要直接崩溃，应写入 `errors` 字段并返回可读错误信息。

---

## 9. 自定义工具设计

工具必须保持“输入清晰、输出结构化、可单独测试”。

### 9.1 unzip_tool

输入：

- ZIP 文件路径
- 输出目录

输出：

- 解压后的项目路径
- 解压文件数量
- 是否成功
- 错误信息

要求：

1. 防止路径穿越攻击。
2. 跳过危险路径。
3. 跳过过大文件。
4. 记录解压日志。

---

### 9.2 repo_scan_tool

输入：

- 项目路径

输出：

- 文件树
- Python 文件列表
- 入口文件候选
- 模型文件候选
- 配置文件候选
- 训练文件候选
- 推理文件候选

---

### 9.3 ast_parse_tool

输入：

- Python 文件路径

输出：

- imports
- aliases
- classes
- functions
- line ranges
- function source code
- class base names
- called symbols
- raw call expressions

---

### 9.4 library_call_extractor_tool

负责从函数源码中识别库函数调用。

输入：

- function source code
- imports
- aliases
- project-defined functions
- project-defined classes

输出：

- library_calls

要求：

1. 支持 `import torch`
2. 支持 `import torch.nn.functional as F`
3. 支持 `import numpy as np`
4. 支持 `import cv2 as cv`
5. 支持 `from PIL import Image`
6. 支持 `from einops import rearrange`
7. 尽量还原 canonical_name
8. 区分外部库函数和项目内部函数
9. 无法确认时标记低置信度

---

### 9.5 library_function_resolver_tool

负责将表面调用名还原成标准函数名。

示例：

```text
F.interpolate → torch.nn.functional.interpolate
np.concatenate → numpy.concatenate
Image.open → PIL.Image.open
rearrange → einops.rearrange
Path.exists → pathlib.Path.exists
```

---

### 9.6 library_doc_lookup_tool

负责在遇到新库函数时获取或生成解释。

MVP 阶段可以先用 LLM 根据函数名和调用上下文生成解释。

后续版本应优先检索官方文档，再让 LLM 总结。

输出必须是教学级解释，不能只给一句空泛说明。

---

### 9.7 model_detect_tool

输入：

- parsed_files
- functions
- classes

输出：

- `nn.Module` 类
- `forward` 函数
- 模型主类候选
- encoder / decoder / backbone / head 候选
- loss 函数候选

---

### 9.8 paper_parse_tool

输入：

- PDF 文件路径

输出：

- 论文标题
- 摘要
- 方法总结
- 核心创新点
- 关键模块
- 关键词

---

### 9.9 mermaid_tool

输入：

- 图类型
- 节点列表
- 边列表

输出：

- Mermaid 代码
- 图说明
- 可选 SVG / PNG 路径

---

### 9.10 report_tool

输入：

- repo_index
- file_analysis
- function_analysis
- model_analysis
- library_function_docs
- paper_analysis
- paper_code_alignment
- diagrams

输出：

- Markdown 报告路径
- 报告正文

---

## 10. Python 库函数识别与全局知识库

### 10.1 功能背景

本项目不仅要分析用户上传代码仓库中的项目文件、类和函数，还需要进一步识别每个函数内部调用的 Python 库函数，例如：

- PyTorch 函数：`torch.cat`、`torch.matmul`、`torch.nn.Linear`、`torch.nn.functional.interpolate`
- NumPy 函数：`np.array`、`np.mean`、`np.concatenate`
- OpenCV 函数：`cv2.imread`、`cv2.resize`
- Python 标准库函数：`os.path.join`、`json.load`、`Path.exists`
- 其他第三方库函数：`PIL.Image.open`、`einops.rearrange`

系统需要在函数级代码分析时识别这些库函数，并将其记录下来。对于未记录过的新库函数，系统需要检索或生成教学级别的解释，并写入一个全局可复用的 Python 函数知识库。

---

### 10.2 函数级库函数调用识别

在分析每一个项目函数时，系统需要识别该函数代码中调用了哪些外部库函数。

例如代码：

```python
def forward(self, x):
    x = self.proj(x)
    x = torch.cat([x, x], dim=1)
    x = F.interpolate(x, scale_factor=2, mode="bilinear")
    return x
```

系统应识别出：

```text
torch.cat
torch.nn.functional.interpolate
```

同时要尽量区分：

1. 项目内部函数调用
2. Python 标准库函数调用
3. 第三方库函数调用
4. PyTorch / NumPy / OpenCV 等深度学习常用库函数调用
5. 类方法调用，例如 `self.proj(x)`，这通常不是库函数，而是模型内部模块调用

---

### 10.3 import 别名解析

系统不能只简单记录代码里的表面名字，而要尽量还原库函数的完整名称。

例如：

```python
import torch.nn.functional as F
F.interpolate(x)
```

应该还原为：

```text
torch.nn.functional.interpolate
```

例如：

```python
import numpy as np
np.concatenate([a, b])
```

应该还原为：

```text
numpy.concatenate
```

例如：

```python
from PIL import Image
Image.open(path)
```

应该还原为：

```text
PIL.Image.open
```

例如：

```python
from einops import rearrange
rearrange(x, "b c h w -> b h w c")
```

应该还原为：

```text
einops.rearrange
```

如果无法完全还原，应记录原始调用名，并设置较低置信度。

---

### 10.4 function_analysis.json 中的 library_calls 字段

在 `function_analysis.json` 中，每个函数都应增加字段：

```json
{
  "library_calls": [
    {
      "canonical_name": "torch.cat",
      "display_name": "torch.cat",
      "package_name": "torch",
      "category": "pytorch",
      "call_text": "torch.cat([x, y], dim=1)",
      "line_no": 58,
      "confidence": "high",
      "is_recorded_in_global_library": true
    }
  ]
}
```

字段说明：

- `canonical_name`：标准函数名，例如 `torch.cat`
- `display_name`：前端显示名，例如 `torch.cat`
- `package_name`：所属包，例如 `torch`
- `category`：类别，例如 `pytorch`、`numpy`、`opencv`、`python_stdlib`
- `call_text`：源码中的调用片段
- `line_no`：调用所在行号
- `confidence`：识别置信度，建议为 `high`、`medium`、`low`
- `is_recorded_in_global_library`：是否已经写入全局函数知识库

---

## 11. 全局 Python 函数知识库

### 11.1 知识库定位

系统需要维护一个全局可见的 Python 函数知识库。

这个知识库不是某个项目独有的，而是所有项目共享。

例如用户在项目 A 中第一次遇到：

```text
torch.cat
```

系统会将 `torch.cat` 的解释写入全局知识库。

之后用户在项目 B、项目 C 中再次遇到 `torch.cat`，系统不需要重新生成解释，而是直接复用已有解释。

---

### 11.2 知识库名称

建议命名为：

```text
Python Function Library
```

中文显示名：

```text
Python 库函数知识库
```

---

### 11.3 library_functions 表结构

MVP 阶段建议使用 SQLite。

推荐表名：

```text
library_functions
```

字段建议：

```text
id
canonical_name
display_name
package_name
category
source_type
summary
beginner_explanation
parameters_explanation
return_explanation
common_usage
code_example
shape_or_tensor_note
common_mistakes
related_functions
official_doc_url
confidence
created_at
updated_at
```

字段说明：

- `canonical_name`：标准函数名，例如 `torch.nn.functional.interpolate`
- `display_name`：前端显示名，例如 `F.interpolate`
- `package_name`：包名，例如 `torch`
- `category`：类别，例如 `pytorch`
- `source_type`：解释来源，例如 `official_doc`、`llm_generated`、`manual`
- `summary`：一句话解释
- `beginner_explanation`：零基础解释
- `parameters_explanation`：常见参数解释
- `return_explanation`：返回值解释
- `common_usage`：常见用途
- `code_example`：简洁示例
- `shape_or_tensor_note`：张量形状相关说明，尤其针对 PyTorch
- `common_mistakes`：常见误区
- `related_functions`：相关函数
- `official_doc_url`：官方文档链接，可选
- `confidence`：解释置信度
- `created_at`：创建时间
- `updated_at`：更新时间

---

### 11.4 library_function_occurrences 表结构

除了记录函数本身，还需要记录它在哪些项目和函数中出现过。

推荐表名：

```text
library_function_occurrences
```

字段建议：

```text
id
library_function_id
task_id
project_name
file_path
function_name
class_name
line_no
call_text
created_at
```

这样系统后续可以支持：

- 这个库函数在哪些项目中出现过？
- 这个项目调用最多的 PyTorch 函数有哪些？
- 用户最近经常遇到哪些还没掌握的库函数？

---

### 11.5 新库函数解释生成流程

当系统在代码中识别到一个库函数时，应按以下流程处理：

```text
识别库函数调用
      ↓
标准化函数名 canonical_name
      ↓
查询全局 Python 函数知识库
      ↓
如果已存在：
    直接关联该函数解释
如果不存在：
    检索官方文档或可信来源
      ↓
    生成教学级解释
      ↓
    写入全局函数知识库
      ↓
    在当前函数分析中引用
```

MVP 阶段可以先使用 LLM 生成解释。

后续版本应优先检索官方文档，再由 LLM 总结，并保存官方文档链接。

---

### 11.6 教学级解释要求

对于新出现的库函数，系统生成解释时必须面向初学者。

解释内容应尽量清晰、明确、通俗、简洁。

每个库函数建议生成以下内容：

1. 一句话作用
2. 通俗解释
3. 常见输入参数
4. 返回值
5. 在深度学习代码中常见用途
6. 简洁代码例子
7. 张量形状变化说明，如适用
8. 常见误区
9. 相关函数

例如 `torch.cat` 的解释应类似：

```text
torch.cat 用来把多个 Tensor 沿着指定维度拼接在一起。

通俗理解：
如果把 Tensor 看成一叠数据表，torch.cat 就是把几张表沿着行方向、列方向或通道方向接起来。

常见参数：
- tensors：要拼接的一组 Tensor
- dim：沿着哪个维度拼接

返回值：
返回拼接后的新 Tensor。

在深度学习中常见用途：
常用于特征融合，例如把两个特征图在通道维度拼接。

形状例子：
如果 x1 和 x2 的形状都是 [B, C, H, W]，
那么 torch.cat([x1, x2], dim=1) 的结果是 [B, 2C, H, W]。

常见误区：
除了拼接的维度外，其他维度必须一致。
```

---

## 12. 前端显示模式

前端页面需要支持两种显示模式：

```text
正常模式
零基础模式
```

### 12.1 正常模式

正常模式面向已有一定基础的用户。

显示内容以代码结构、函数作用、模型位置、实现逻辑为主。

库函数说明默认不展开，只在需要时显示。

---

### 12.2 零基础模式

零基础模式面向初学者。

在分析每个函数时，页面应额外显示该函数调用的 Python 库函数列表。

例如：

```text
当前函数调用的库函数：
- torch.cat
- torch.nn.functional.interpolate
- einops.rearrange
```

这些库函数名应支持点击。

点击后弹出说明弹窗。

弹窗中显示该库函数的教学级解释。

---

### 12.3 库函数弹窗设计

点击库函数名后，弹窗建议显示：

```text
函数名：torch.cat

一句话作用：
把多个 Tensor 沿着指定维度拼接起来。

通俗解释：
可以理解为把几块特征图接在一起。

常见参数：
- tensors：需要拼接的 Tensor 列表
- dim：在哪个维度拼接

返回值：
拼接后的 Tensor。

深度学习中常见用途：
常用于特征融合，尤其是在通道维度拼接多个特征。

形状变化：
如果两个输入都是 [B, C, H, W]，
torch.cat([x1, x2], dim=1) 得到 [B, 2C, H, W]。

常见误区：
除了 dim 指定的维度外，其他维度必须相同。
```

弹窗要求：

1. 信息清楚。
2. 不要太长。
3. 支持关闭。
4. 支持跳转到全局函数知识库详情页。
5. 如果解释来源于官方文档，应可显示官方链接。
6. 如果解释置信度较低，应提示“该解释可能需要人工确认”。

---

### 12.4 全局函数知识库页面

前端后续应增加一个全局页面：

```text
Python 函数库
```

该页面展示所有已经记录的库函数。

支持功能：

1. 按包筛选：PyTorch、NumPy、OpenCV、Python 标准库等。
2. 按关键词搜索。
3. 查看函数详情。
4. 查看该函数在哪些项目中出现过。
5. 查看最近新增函数。
6. 查看高频函数。
7. 查看低置信度、待确认函数。

这部分可以作为后续版本实现，不要求 v0.1 完成。

---

## 13. Pydantic 数据模型建议

### 13.1 LibraryCall

```python
from typing import Literal
from pydantic import BaseModel

class LibraryCall(BaseModel):
    canonical_name: str
    display_name: str
    package_name: str | None = None
    category: str | None = None
    call_text: str
    line_no: int | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    is_recorded_in_global_library: bool = False
```

---

### 13.2 LibraryFunctionDoc

```python
from typing import Literal
from pydantic import BaseModel

class LibraryFunctionDoc(BaseModel):
    canonical_name: str
    display_name: str
    package_name: str | None = None
    category: str | None = None

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
    source_type: str = "llm_generated"
    confidence: Literal["high", "medium", "low"] = "medium"
```

---

### 13.3 FunctionAnalysis

```python
class FunctionAnalysis(BaseModel):
    file_path: str
    class_name: str | None = None
    function_name: str
    start_line: int | None = None
    end_line: int | None = None

    purpose: str
    inputs: list[str] = []
    outputs: list[str] = []
    implementation_logic: list[str] = []
    computation_logic: list[str] = []
    model_position: str | None = None

    called_internal_functions: list[str] = []
    library_calls: list[LibraryCall] = []

    is_core_function: bool = False
    beginner_explanation: str | None = None
```

---

## 14. 输出标准

最终系统至少要能输出以下内容：

```text
outputs/{task_id}/
  repo_index.json
  parsed_files.json
  library_calls.json
  library_function_docs.json
  function_analysis.json
  file_analysis.json
  model_analysis.json
  paper_analysis.json
  paper_code_alignment.json
  diagrams.json
  report.md
```

后续版本增加：

```text
outputs/{task_id}/
  report.pdf
  model_diagram.svg
  project_graph.svg
```

---

## 15. 开发阶段规划

### v0.1：最小 LangGraph + 工具链闭环

目标：

跑通最小工作流。

功能：

1. 上传 ZIP 或指定本地 ZIP 路径。
2. 解压 ZIP。
3. 扫描项目目录。
4. 提取 Python 文件。
5. 用 AST 解析 import / class / function。
6. 保存 `repo_index.json`。
7. 生成简单 `report.md`。
8. 整个流程由 LangGraph 串联。

验收标准：

- 能分析一个小型 PyTorch 项目。
- 能生成目录树。
- 能列出所有 Python 文件。
- 能列出每个文件的类和函数。
- 能输出 `repo_index.json` 和 `report.md`。
- 每个工具可以单独测试。

---

### v0.2：文件级分析

目标：

让系统能解释每个文件的作用。

功能：

1. 对每个 Python 文件生成文件说明。
2. 判断文件类型：模型、训练、推理、数据、配置、工具。
3. 输出 `file_analysis.json`。
4. 报告中增加“逐文件分析”章节。

验收标准：

- 每个文件都有作用说明。
- 核心模型文件能被初步识别。
- 报告内容适合初学者阅读。

---

### v0.3：函数级分析 + library_calls 基础识别

目标：

让系统能解释每个函数，并识别函数内部调用的库函数。

功能：

1. 对每个函数生成作用说明。
2. 解释输入、输出、实现逻辑、计算逻辑。
3. 标记核心函数。
4. 识别函数内部调用的 Python / PyTorch / NumPy 等库函数。
5. 在函数分析结果中增加 `library_calls` 字段。
6. 输出 `function_analysis.json` 和 `library_calls.json`。

验收标准：

- 每个函数都有结构化解释。
- `forward`、`train`、`inference`、`loss` 等函数能被重点分析。
- 能识别常见 alias，例如 `F.interpolate`、`np.concatenate`。
- 能区分一部分项目内部函数和第三方库函数。
- 解释语言要通俗，适合初学者。

---

### v0.4：全局 Python 函数知识库 MVP

目标：

实现跨项目复用的 Python 库函数知识库。

功能：

1. 使用 SQLite 存储 `library_functions`。
2. 使用 SQLite 存储 `library_function_occurrences`。
3. 遇到新库函数时自动生成简洁教学级解释。
4. 同一函数跨项目复用解释。
5. 记录库函数出现在哪个项目、文件、函数、行号。
6. 提供基础查询接口。

验收标准：

- 同一个库函数不会重复生成解释。
- 新库函数能自动入库。
- 函数分析结果能关联全局函数库。
- 能查询某个库函数在哪些项目中出现过。

---

### v0.5：模型网络识别

目标：

识别 PyTorch 模型结构。

功能：

1. 识别 `nn.Module` 子类。
2. 识别 `__init__` 中定义的网络层。
3. 识别 `forward` 中的数据流。
4. 生成模型主流程。
5. 输出 `model_analysis.json`。
6. 生成基础 Mermaid 模型图。

验收标准：

- 能找到模型主类。
- 能解释输入如何经过网络变成输出。
- 能生成可读的模型流程图。
- 图中的节点要能对应到真实代码。

---

### v0.6：论文解析与论文代码对齐

目标：

支持可选论文 PDF。

功能：

1. 解析论文 PDF。
2. 提取论文核心创新点。
3. 提取论文方法模块。
4. 将论文创新点和代码文件、类、函数进行对齐。
5. 输出 `paper_analysis.json` 和 `paper_code_alignment.json`。
6. 报告中增加“论文创新点对齐”章节。

验收标准：

- 有论文时进行论文对齐。
- 无论文时系统仍可正常分析代码。
- 对齐结果必须包含置信度。
- 不确定的对应关系不能强行确认。

---

### v0.7：图生成增强

目标：

生成更清楚的模型图和代码结构图。

功能：

1. 生成项目结构图。
2. 生成模型整体流程图。
3. 生成核心模块图。
4. 生成函数逻辑图。
5. 输出 Mermaid 代码。
6. 可选渲染 SVG / PNG。

验收标准：

- 图结构清楚。
- 图节点来自真实代码或论文模块。
- 图说明通俗易懂。
- 图可以直接放入报告。

---

### v0.8：前端零基础模式

目标：

实现正常模式 / 零基础模式切换。

功能：

1. 前端支持正常模式和零基础模式。
2. 函数详情页显示 `library_calls`。
3. 点击库函数名弹出教学级解释弹窗。
4. 可跳转到全局函数库详情页。

验收标准：

- 正常模式简洁。
- 零基础模式解释更详细。
- 库函数弹窗清楚、简洁、适合初学者。
- 前端能从后端接口读取库函数解释。

---

### v0.9：全局 Python 函数库页面

目标：

提供全局函数知识库管理页面。

功能：

1. 搜索库函数。
2. 按包筛选。
3. 查看函数详情。
4. 查看函数出现历史。
5. 查看高频函数。
6. 查看低置信度函数。
7. 后续可支持人工编辑解释。

验收标准：

- 能查看所有已记录库函数。
- 能搜索 `torch.cat` 等函数。
- 能查看某个函数出现在哪些项目中。
- 能作为用户个人学习知识库使用。

---

### v1.0：完整 Web 系统与报告导出

目标：

形成可展示的完整项目。

功能：

1. 前端上传 ZIP 和 PDF。
2. 后端创建分析任务。
3. 展示分析进度。
4. 展示项目总览、文件分析、函数分析、模型图、论文对齐。
5. 支持正常模式和零基础模式。
6. 支持下载 Markdown / PDF 报告。
7. 支持查看历史任务。
8. 支持查看全局 Python 函数库。

验收标准：

- 可通过浏览器完整使用。
- 有 README 和演示截图。
- 有测试样例。
- 有项目架构文档。
- 能作为简历项目展示。

---

## 16. 编码规范

### 16.1 代码风格

- 使用 Python 3.11 或以上。
- 使用类型注解。
- 使用 Pydantic 定义核心数据结构。
- 函数职责要单一。
- 避免一个函数超过 80 行。
- 复杂逻辑必须写注释。
- 文件名、函数名、变量名要清晰。
- 不要写无意义缩写。

---

### 16.2 错误处理

所有工具函数都要处理异常。

错误信息应包含：

- 错误发生在哪个工具
- 输入路径或文件
- 错误类型
- 简短错误说明

不要让整个系统因为一个文件解析失败就全部中断。某个文件失败时，应记录错误并继续分析其他文件。

---

### 16.3 路径安全

ZIP 解压必须防止路径穿越攻击。

禁止让 ZIP 中的文件解压到目标目录外。

需要过滤：

- `../`
- 绝对路径
- 隐藏系统目录
- 超大文件
- 权重文件
- 数据集文件
- 输出文件夹

---

### 16.4 大文件处理

默认跳过以下文件：

```text
.pt
.pth
.ckpt
.onnx
.mp4
.avi
.mov
.png
.jpg
.jpeg
.npy
.npz
.zip
.tar
.gz
```

默认跳过以下目录：

```text
.git
__pycache__
.ipynb_checkpoints
data
datasets/raw
outputs
logs
checkpoints
weights
```

---

## 17. Prompt 设计规范

所有 Agent Prompt 都要放在：

```text
backend/app/prompts/
```

不要把长 Prompt 直接写死在 Python 代码里。

每个 Prompt 应该包含：

1. 角色定位
2. 输入数据说明
3. 输出格式要求
4. 禁止事项
5. 示例输出

建议 Prompt 文件包括：

```text
function_analyzer.md
file_analyzer.md
model_analyzer.md
library_function_doc_writer.md
paper_analyzer.md
paper_code_aligner.md
report_writer.md
```

输出格式要尽量稳定，优先使用 JSON 或固定 Markdown 模板。

---

## 18. 分析结果语言风格

分析报告主要面向初学者，因此语言要求：

- 通俗易懂
- 不堆术语
- 先讲作用，再讲细节
- 先讲整体，再讲局部
- 对深度学习模块要解释“它在网络中干什么”
- 对核心函数要解释“输入是什么、输出是什么、数据怎么变”
- 对 PyTorch 库函数要适当说明
- 不确定时明确说明“不确定”或“可能是”

禁止使用以下风格：

- 空泛总结
- 只翻译函数名
- 只说“该函数用于处理数据”
- 不说明输入输出
- 不说明在模型中的位置
- 强行把代码和论文对应起来
- 把项目内部函数随便当成第三方库函数

---

## 19. 测试要求

每个阶段都要补充基础测试。

至少包含：

- ZIP 解压测试
- 文件扫描测试
- AST 解析测试
- 函数抽取测试
- library call 提取测试
- import alias 解析测试
- 全局函数知识库读写测试
- `nn.Module` 检测测试
- LangGraph 工作流测试

测试样例放在：

```text
examples/
```

测试文件放在：

```text
tests/
```

不要只用大型真实仓库测试。必须准备一个小型 PyTorch 示例项目，方便快速验证。

---

## 20. 文档要求

项目必须维护以下文档：

```text
README.md
docs/requirement.md
docs/architecture.md
docs/agent_workflow.md
docs/api.md
docs/database.md
docs/development_plan.md
```

README 至少包含：

1. 项目介绍
2. 核心功能
3. 技术栈
4. 快速开始
5. 使用示例
6. 输出示例
7. 项目结构
8. 开发路线
9. 简历亮点

---

## 21. API 设计建议

### 21.1 分析任务接口

```text
POST /analysis/tasks
GET /analysis/tasks/{task_id}
GET /analysis/tasks/{task_id}/report
GET /analysis/tasks/{task_id}/functions
GET /analysis/tasks/{task_id}/files
GET /analysis/tasks/{task_id}/diagrams
```

---

### 21.2 函数库接口

```text
GET /library/functions
GET /library/functions/{id}
GET /library/functions/by-name/{canonical_name}
GET /library/functions/{id}/occurrences
GET /analysis/{task_id}/functions/{function_id}/library-calls
```

---

## 22. 简历展示目标

最终项目应该能在简历中体现以下能力：

1. 基于 LangGraph 的多节点 Agent 工作流设计能力。
2. 自定义工具链开发能力。
3. 代码静态分析能力。
4. Python / PyTorch 库函数识别能力。
5. 全局函数知识库设计能力。
6. PyTorch 模型结构识别能力。
7. 论文解析与论文代码对齐能力。
8. RAG 检索与结构化知识管理能力。
9. Mermaid / Graphviz 图生成能力。
10. Markdown / PDF 报告生成能力。
11. FastAPI 后端系统开发能力。
12. 前后端联动和产品化设计能力。
13. 工程化目录组织、测试、文档和异常处理能力。

简历项目描述方向：

```text
CodeResearch Agent：基于 LangGraph 的深度学习代码仓库与论文联合分析系统
```

推荐简历描述：

```text
- 设计并实现基于 LangGraph 的多节点 Agent 工作流，支持上传代码 ZIP 与论文 PDF，自动完成代码结构解析、函数级解释、模型网络识别、论文创新点对齐与技术报告生成。
- 基于 Python AST 构建代码静态分析工具链，抽取文件结构、类、函数、import 依赖、调用关系与 PyTorch nn.Module 模型结构。
- 设计并实现 Python / PyTorch 库函数识别与全局知识库模块，基于 AST 调用表达式与 import alias 解析，自动识别函数内部调用的第三方库函数，并将高频库函数沉淀为跨项目复用的教学级知识库。
- 支持正常模式与零基础模式，零基础模式下可查看当前函数调用的库函数，并通过弹窗展示库函数作用、参数、返回值、张量形状变化和常见误区。
- 支持自动生成 Mermaid 模型结构图和 Markdown / PDF 教学化报告，提升深度学习开源项目阅读效率。
```

---

## 23. 禁止事项

开发过程中不要做以下事情：

1. 不要一次性实现所有功能。
2. 不要把所有代码写在一个文件里。
3. 不要把所有逻辑写成一个巨大 Prompt。
4. 不要直接让大模型读取整个仓库后自由总结。
5. 不要忽略中间 JSON 产物。
6. 不要没有测试就继续加复杂功能。
7. 不要在没有证据时强行论文代码对齐。
8. 不要让图里的模块无法追溯到代码。
9. 不要为了炫技引入过多暂时用不到的框架。
10. 不要牺牲可读性和可维护性。
11. 不要把项目内部函数误判为第三方库函数。
12. 不要让全局函数知识库变成不可更新的死数据。
13. 不要在零基础模式下输出大段难懂解释。

---

## 24. 当前优先任务

当前优先实现 v0.1。

v0.1 的目标不是完整系统，而是跑通 LangGraph + 自定义工具链的最小闭环。

请优先完成：

1. 创建基础项目结构。
2. 创建 FastAPI 后端骨架。
3. 创建 LangGraph 工作流。
4. 实现 `unzip_tool`。
5. 实现 `repo_scan_tool`。
6. 实现 `ast_parse_tool`。
7. 定义 `AgentState`。
8. 实现 `UnzipNode`、`RepoScanNode`、`CodeParseNode`、`ReportGenerateNode`。
9. 生成 `repo_index.json`。
10. 生成简单 `report.md`。
11. 添加基础测试。
12. 更新 README。

v0.1 完成后，再进入 v0.2 文件级分析。

不要在 v0.1 阶段提前实现论文解析、前端零基础模式或全局函数库页面。

---

## 25. 每次开发后的交付要求

每完成一个阶段，需要输出：

1. 本阶段实现了什么。
2. 修改了哪些文件。
3. 如何运行。
4. 如何测试。
5. 当前输出文件在哪里。
6. 已知问题。
7. 下一阶段建议。

每次修改代码后，要优先保证：

- 项目能启动。
- 核心测试能通过。
- README 或相关文档同步更新。
- 不破坏已有功能。

---

## 26. 最终目标

本项目最终要成为一个既能自用、又能展示的工程项目。

对用户来说，它应该是一个读论文代码的学习助手。

对简历来说，它应该展示的是：

- Agent 系统设计能力
- LangGraph 工作流编排能力
- 工具调用能力
- 代码静态分析能力
- Python / PyTorch 函数知识库设计能力
- 深度学习工程理解能力
- 论文代码对齐能力
- 复杂项目拆解和工程化落地能力

因此，任何实现都要围绕这个目标展开。
