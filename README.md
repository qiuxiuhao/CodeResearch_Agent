# CodeResearch Agent

CodeResearch Agent 是一个本地优先的代码理解 Agent，面向深度学习代码仓库和可选的论文 PDF。它可以把一个项目 ZIP 转换成结构化分析结果、Markdown 报告、Mermaid 图示、可检索的 Python 函数知识库，以及一个可交互的 React 工作台。

当前版本：`1.2.3`

## 核心亮点

- 使用 LangGraph 组织分阶段代码分析工作流。
- 基于 Python AST 做静态分析，提取 import、alias、类、函数、方法和行号范围。
- 生成文件级分析和函数级分析，并尽量保留 evidence。
- 识别 Python / PyTorch / NumPy / PIL / OpenCV / einops 等库函数调用。
- 使用 SQLite 沉淀全局 Python 函数教学知识库。
- 为零基础用户生成教学级库函数解释。
- 识别 PyTorch 风格的 `nn.Module` 模型类、网络层和基础 forward 流程。
- 支持可选论文 PDF 解析，并启发式对齐论文贡献点和代码结构。
- 本地确定性提取论文 Figure、图注、页码、bbox、原始资产和 canonical preview。
- 可独立启用 Qwen-VL（默认）/GLM-4.5V（备用）理解筛选后的关键 Figure。
- 生成 Mermaid 图示，包括项目结构、模型流程、核心模块、函数逻辑和论文代码对齐。
- 提供 React + Vite 前端，支持正常模式、零基础模式、任务结果浏览和全局函数库搜索。

v1.2.3 在 v1.2.2 的 Figure 提取与可选 VLM 理解基础上，补强建议代码链接校验、Vision 缓存故障回退、共享 PDF 安全限制和 Figure 提取兼容性。文本 LLM 和论文 VLM 仍可独立启用并分别授权。当前仍不包含教学图生成、图片重绘、视频、登录、复杂部署、PDF 导出或复杂 RAG。

## v1.1 LLM 增强

- 文件、函数、模型和论文代码对齐解释默认使用 DeepSeek，失败后回退 Qwen。
- 所有调用通过 ModelRouter，输出经过 Pydantic 和 evidence 引用校验。
- 规则事实不会被 LLM 覆盖，增强结果独立保存在 `llm_explanations.json`。
- 后端强制验证 `external_model_consent`，并独立限制逻辑实体数和真实 Provider 请求数。
- 发送前过滤常见密钥、token、password、私钥和连接字符串；不记录完整 Prompt、源码或原始响应。
- 自动测试只使用 MockProvider；真实连通性只能手动运行 `scripts/smoke_llm.py`。

## v1.2 论文 Figure 理解

- Python/PyMuPDF 在本地确定性检测图注、页码、Figure bbox、原始图片对象和正文 Figure 引用。
- 前端和 VLM 默认使用完整 Figure bbox 的页面区域渲染图，避免丢失 PDF 文字、矢量箭头、多 panel 和图例。
- VLM 只输出 Figure 类型、模块、流程、输入输出、视觉关系、贡献候选和不确定性，并通过 Pydantic/evidence 校验。
- 默认路由为 Qwen-VL，失败后回退 GLM-4.5V；首版使用纯 JSON Prompt 与本地解析，不默认开启 JSON Object。
- `text_llm_enabled` 与 `vision_vlm_enabled`、`external_text_consent` 与 `external_vision_consent` 相互独立。
- 自动测试只使用 MockVisionProvider；真实图片请求只能手动运行 `scripts/smoke_vlm.py`。

## 截图

本仓库暂不强制提交截图。推荐截图清单和采集说明见 [docs/screenshots.md](docs/screenshots.md)。

## 技术栈

- 后端：Python 3.11、FastAPI、LangGraph、Pydantic、PyMuPDF
- 静态分析：Python `ast`、确定性规则工具
- 存储：SQLite，用于全局 Python 函数知识库
- 前端：React、Vite、TypeScript、Mermaid、lucide-react
- 测试：pytest、Vitest、Testing Library

## 快速开始

创建并安装后端环境：

```bash
conda create -n code-research-agent python=3.11 -y
conda activate code-research-agent
pip install -e ".[dev]"
```

安装前端依赖：

```bash
npm --prefix frontend ci
```

不要提交 `frontend/node_modules/`。前端依赖应通过 `frontend/package-lock.json` 和 `npm ci` 恢复。

一键启动后端和前端：

```bash
bash scripts/dev.sh
```

打开：

```text
http://127.0.0.1:5173
```

后端健康检查：

```text
http://127.0.0.1:8000/health
```

手动启动方式：

```bash
conda run -n code-research-agent uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## 演示流程

使用内置示例：

```text
examples/small_pytorch_project.zip
```

推荐演示步骤：

1. 执行 `bash scripts/dev.sh`。
2. 打开 `http://127.0.0.1:5173`。
3. 使用路径模式，输入 `examples/small_pytorch_project.zip`。
4. 创建分析任务。
5. 依次查看总览、文件、函数、库函数说明、模型分析、图示、全局函数库和报告。
6. 切换到零基础模式，点击函数中的库函数调用，打开教学解释弹窗。

更多说明见 [docs/demo_guide.md](docs/demo_guide.md)。

## API

核心 API：

- `GET /health`
- `POST /analysis/tasks`
- `POST /analysis/tasks/upload`
- `GET /analysis/tasks`
- `GET /analysis/tasks/{task_id}`
- `GET /analysis/tasks/{task_id}/report`
- `GET /analysis/tasks/{task_id}/figures/{figure_id}/preview`
- `GET /analysis/tasks/{task_id}/figures/{figure_id}/assets/{asset_id}`
- `GET /llm/public-config`
- `GET /vision/public-config`
- `GET /library/stats`
- `GET /library/functions`
- `GET /library/functions/{canonical_name}`
- `GET /library/functions/low-confidence`

完整 API 说明见 [docs/api_reference.md](docs/api_reference.md)。

## 输出文件

每次分析会写入：

```text
outputs/{task_id}/
  source/
  repo_index.json
  parsed_files.json
  file_analysis.json
  library_calls.json
  function_analysis.json
  model_analysis.json
  paper_analysis.json
  paper_code_alignment.json
  paper_figure_analysis.json
  paper_figures/original/
  paper_figures/previews/
  diagrams.json
  library_function_docs.json
  llm_explanations.json
  report.md
```

这些任务输出属于运行时产物，不应提交到 Git。

## 全局函数库

全局函数库的定位是“Python / PyTorch 库函数教学知识库”。它记录库函数本身的教学级解释，支持搜索、筛选、详情查看和零基础模式弹窗，不记录某个库函数在每个项目、文件、函数或行号中的出现位置。

默认 SQLite 数据库路径：

```text
data/python_function_library.sqlite3
```

可以通过 `LIBRARY_DB_PATH`、`--library-db-path` 或 API 请求字段覆盖。 SQLite 文件属于本地运行时数据，不应提交。

更多说明见 [docs/database.md](docs/database.md)。

## 测试与验收

运行完整验收脚本：

```bash
bash scripts/validate.sh
```

手动运行后端测试：

```bash
python -m pytest -q
```

手动运行前端测试和构建：

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

也可以进入前端目录执行：

```bash
cd frontend
npm ci
npm test
npm run build
```

`npm run build` 时 Mermaid 可能产生构建体积警告，这不影响 v1.2 前端运行。后续版本可以通过 dynamic import 或 code splitting 优化体积。

真实 VLM 连通性测试会发送一张无敏感信息的合成图并可能产生费用，不属于自动验收：

```bash
python scripts/smoke_vlm.py --provider qwen_vl --i-understand-cost
python scripts/smoke_vlm.py --provider glm_v --i-understand-cost
```

## 项目结构

```text
backend/
  app/
    agents/      LangGraph 图和节点
    schemas/     Pydantic 数据模型
    services/    分析服务和 SQLite 服务
    tools/       确定性分析工具
frontend/
  src/
    api/         API client
    components/  React 面板和复用组件
    types/       TypeScript 分析结果类型
docs/            架构、API、演示、简历、面试、FAQ 文档
examples/        示例项目 ZIP
plan/            分阶段开发计划
scripts/         本地启动和验收脚本
```

## 文档

- [架构说明](docs/architecture.md)
- [Agent 工作流](docs/agent_workflow.md)
- [API 参考](docs/api_reference.md)
- [数据库说明](docs/database.md)
- [演示指南](docs/demo_guide.md)
- [前端指南](docs/frontend_guide.md)
- [截图说明](docs/screenshots.md)
- [简历描述](docs/resume.md)
- [面试讲解](docs/interview_guide.md)
- [FAQ](docs/faq.md)
- [验收说明](docs/validation.md)

## 简历描述

CodeResearch Agent 是一个基于 FastAPI + LangGraph + React 的深度学习代码理解工具，支持 AST 仓库分析、函数/模型结构提取、可选论文代码对齐、Mermaid 图示，以及带零基础解释的 SQLite 全局 Python 函数知识库。

更完整的简历表述和面试讲解提纲见 [docs/resume.md](docs/resume.md) 和 [docs/interview_guide.md](docs/interview_guide.md)。

## 提交前清理

```bash
bash scripts/clean.sh
```
