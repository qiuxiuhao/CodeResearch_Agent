# v0.1 开发计划：LangGraph + 自定义工具链最小闭环

## 阶段目标

v0.1 跑通最小后端闭环：输入本地 ZIP 路径，安全解压，扫描项目目录，解析 Python 文件的 import、class、function 和 line range，通过 LangGraph 串联节点，并输出 `repo_index.json`、`parsed_files.json`、`report.md`。

## 本阶段不做什么

不做论文解析、论文代码对齐、前端、零基础模式、全局函数知识库、库函数教学解释、模型图、Mermaid 图、PDF 导出、RAG、历史任务和复杂异步队列。

## 统一 Python 环境

整个项目共用一个 Conda 环境：

```bash
conda create -n code-research-agent python=3.11 -y
conda activate code-research-agent
pip install -e ".[dev]"
```

后续阶段继续使用 `code-research-agent`，不按阶段创建新环境。

## 新增和修改文件

本阶段新增基础配置、后端骨架、工具、LangGraph 节点、服务、schema、测试和示例项目。主要路径包括：

```text
pyproject.toml
README.md
backend/app/
tests/
examples/small_pytorch_project.zip
outputs/
```

不修改 `AGENTS.md`。

## 核心设计

- `tools`：确定性工具，负责解压、扫描、AST 解析、报告生成。
- `nodes`：LangGraph 节点，只做 State 输入输出适配。
- `services`：任务编排、输出目录管理、CLI/API 调用入口。
- `schemas`：统一数据结构，保证 JSON 产物稳定。

## AgentState

```python
class AgentState(TypedDict, total=False):
    task_id: str
    zip_path: str
    repo_path: str
    output_dir: str
    file_tree: dict
    python_files: list[str]
    repo_index: dict
    parsed_files: list[dict]
    functions: list[dict]
    classes: list[dict]
    report_md: str
    errors: list[dict]
```

## 自定义工具

- `unzip_tool`：安全解压 ZIP，防止路径穿越，跳过危险文件。
- `repo_scan_tool`：扫描目录、生成文件树、识别候选文件。
- `ast_parse_tool`：解析 Python import、alias、class、function、line range 和源码片段。
- `report_tool`：根据结构化结果生成 Markdown 报告。

## LangGraph 节点

```text
START -> UnzipNode -> RepoScanNode -> CodeParseNode -> ReportGenerateNode -> END
```

## 输出文件

每次任务输出到：

```text
outputs/{task_id}/
  repo_index.json
  parsed_files.json
  report.md
```

## 测试计划

- 解压工具测试：正常 ZIP、路径穿越、危险文件跳过。
- 扫描工具测试：目录树、Python 文件、候选类型、跳过规则。
- AST 工具测试：import alias、class、function、method、语法错误。
- LangGraph 集成测试：示例项目 ZIP 完整跑通。

## 运行方式

```bash
python -m backend.app.services.analysis_service examples/small_pytorch_project.zip
uvicorn backend.app.main:app --reload
pytest
```

## 验收标准

能在统一 Conda 环境 `code-research-agent` 中运行；能分析小型 PyTorch 项目 ZIP；能生成目录树、Python 文件列表、类和函数列表；能输出 `repo_index.json`、`parsed_files.json`、`report.md`；工具和 LangGraph 工作流测试通过。

## 风险和解决方案

- ZIP 路径穿越：解压前校验目标路径必须在任务目录内。
- 语法错误文件：记录到 `errors`，不中断流程。
- 扫描误纳入大文件：默认跳过权重、数据、缓存和二进制文件。
- 环境污染：整个项目只使用 `code-research-agent` Conda 环境。

## 执行顺序

创建配置和目录骨架，定义 State/schema，实现 utils 和 tools，实现节点和 graph，实现服务和 API，创建示例 ZIP，补测试，更新 README，在统一 Conda 环境中运行验收。

