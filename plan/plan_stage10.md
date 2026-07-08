# v1.0 开发计划：项目收尾、演示优化与简历级交付

## 1. 阶段目标

v1.0 不继续增加复杂分析能力，重点把 CodeResearch Agent 整理成一个可以长期自用、可以 GitHub 展示、可以求职简历使用、可以面试讲解的完整工程项目。

本阶段目标：

- 统一版本号为 `1.0.0`。
- 提供一键启动后端和前端的脚本。
- 提供一键验收脚本。
- 整理 GitHub 首页级 README。
- 补充项目架构、Agent 工作流、API、数据库、前端、演示、简历、面试、FAQ 和验收文档。
- 明确示例项目演示流程。
- 清理缓存、构建产物、本地数据库和临时输出。
- 保持现有后端分析流程和前端核心功能稳定。

## 2. 本阶段不做什么

v1.0 不做：

- 不继续增加复杂新分析功能。
- 不重构已经稳定的 LangGraph 主流程。
- 不实现用户登录系统。
- 不实现复杂部署系统、Docker Compose、Nginx 或云部署脚本。
- 不实现 PDF 导出。
- 不实现 RAG 增强、向量数据库或官方文档在线检索。
- 不实现人工编辑全局函数库。
- 不实现 Graphviz、PNG、SVG 图导出。
- 不提交运行时生成的任务输出、本地 SQLite、缓存或构建产物。

## 3. 预计新增和修改的文件

新增文件：

```text
plan/plan_stage10.md
scripts/dev.sh
scripts/validate.sh
docs/architecture.md
docs/agent_workflow.md
docs/api_reference.md
docs/database.md
docs/demo_guide.md
docs/frontend_guide.md
docs/screenshots.md
docs/resume.md
docs/interview_guide.md
docs/faq.md
docs/validation.md
```

修改文件：

```text
README.md
pyproject.toml
backend/app/main.py
backend/app/tools/report_tool.py
frontend/package.json
frontend/package-lock.json
.gitignore
```

原则上不修改：

```text
AGENTS.md
backend/app/agents/graph.py
backend/app/agents/nodes/*
backend/app/tools/* 分析逻辑
backend/app/services/analysis_service.py 主流程
frontend/src/components/* 核心业务页面
```

除非测试暴露明确的版本字符串遗漏，否则 v1.0 不改稳定业务逻辑。

## 4. README 最终结构设计

README 需要整理为 GitHub 首页级文档，建议结构：

1. 项目简介：一句话说明这是“面向深度学习仓库和论文的代码理解 Agent”。
2. 核心亮点：LangGraph、AST 静态分析、函数/文件/模型分析、全局函数库、论文对齐、Mermaid 图示、React 前端。
3. 功能截图占位：链接到 `docs/screenshots.md`。
4. 技术栈。
5. 快速开始：后端环境、前端依赖、一键启动。
6. 演示流程：使用 `examples/small_pytorch_project.zip`。
7. API 简介：链接 `docs/api_reference.md`。
8. 输出文件说明。
9. 测试与验收：`bash scripts/validate.sh` 和手动命令。
10. 项目结构。
11. 路线图与不做事项。
12. 简历描述与面试讲解链接。

## 5. docs 文档结构设计

新增 `docs/` 文档集：

- `docs/architecture.md`：系统分层、数据流、模块边界。
- `docs/agent_workflow.md`：LangGraph 节点顺序、输入输出和结构化产物。
- `docs/api_reference.md`：`/analysis/*`、`/library/*` API 说明和示例。
- `docs/database.md`：SQLite 默认路径、表结构说明、运行时数据不提交。
- `docs/demo_guide.md`：从启动到完成一次演示的完整步骤。
- `docs/frontend_guide.md`：正常模式、零基础模式、全局函数库和 Mermaid 图示说明。
- `docs/screenshots.md`：截图清单占位和采集说明。
- `docs/resume.md`：简历项目描述短版、长版、技术关键词。
- `docs/interview_guide.md`：3 分钟、8 分钟、15 分钟讲解提纲。
- `docs/faq.md`：常见问题和设计取舍。
- `docs/validation.md`：测试、构建、演示验收和清理命令。

## 6. 一键启动方案

新增 `scripts/dev.sh`：

- 使用 `conda run -n code-research-agent uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000` 启动后端。
- 使用 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` 启动前端。
- 脚本从仓库根目录执行。
- `Ctrl+C` 时清理两个子进程。
- 输出访问地址：
  - 前端：`http://127.0.0.1:5173`
  - 后端健康检查：`http://127.0.0.1:8000/health`

新增 `scripts/validate.sh`：

- 顺序执行后端测试、前端依赖安装、前端测试、前端构建。
- 不自动删除用户数据，只在末尾提示清理命令。

## 7. 示例演示流程设计

默认示例：

```text
examples/small_pytorch_project.zip
```

推荐演示流程：

1. 执行 `bash scripts/dev.sh`。
2. 打开 `http://127.0.0.1:5173`。
3. 使用路径模式填入 `examples/small_pytorch_project.zip`。
4. 创建分析任务。
5. 展示总览页。
6. 展示文件级分析。
7. 展示函数级分析。
8. 切换零基础模式，点击库函数解释弹窗。
9. 展示模型网络结构分析。
10. 展示图示分析。
11. 展示全局函数库页面。
12. 展示报告页。

## 8. GitHub 展示内容设计

GitHub 首页应突出：

- 项目定位：面向深度学习代码和论文的代码理解 Agent。
- 工程复杂度：FastAPI + LangGraph + SQLite + React + Vite。
- 可解释性：输出 JSON、Markdown、Mermaid、前端页面。
- 可追溯性：每类分析尽量保留 evidence、confidence、source refs。
- 演示友好：一键启动、示例 ZIP、截图说明、demo guide。
- 范围边界：明确不包含登录、复杂部署、RAG、PDF 导出。

## 9. 简历项目描述设计

短版：

```text
CodeResearch Agent：基于 FastAPI、LangGraph、AST 静态分析和 React 的深度学习代码理解工具，支持仓库结构解析、函数/模型分析、论文代码对齐、全局 Python 函数知识库和可视化报告。
```

长版要突出：

- 设计并实现多节点 LangGraph 分析工作流。
- 使用 AST 静态分析提取文件、类、函数、库函数调用和模型结构。
- 使用 SQLite 沉淀 Python / PyTorch / NumPy 函数教学解释。
- 支持论文 PDF MVP 解析和贡献点到代码结构的启发式对齐。
- 使用 Mermaid 生成项目结构、模型流程、函数逻辑等图示。
- 实现 React 前端，支持正常模式 / 零基础模式和全局函数库检索。

## 10. 面试讲解提纲设计

3 分钟讲解：

- 项目解决什么问题。
- 核心流程：上传 ZIP -> 静态分析 -> JSON/report -> 前端展示。
- 自己负责的关键技术点和结果。

8 分钟讲解：

- 架构分层。
- LangGraph 工作流。
- AST 静态分析与确定性规则。
- SQLite 全局函数库。
- 前端双模式体验。
- 难点和取舍。

15 分钟讲解：

- 详细展开 schema、node、tool、service 分层。
- 解释为什么不一开始依赖大 prompt 或 RAG。
- 展示模型识别、论文对齐、Mermaid 图生成的可追溯设计。
- 说明 v1.0 后续可扩展方向。

## 11. 测试和验收计划

后端：

```bash
conda run -n code-research-agent pytest -q
```

前端：

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

一键验收：

```bash
bash scripts/validate.sh
```

启动验收：

```bash
bash scripts/dev.sh
```

手动演示验收：

- 使用 `examples/small_pytorch_project.zip` 创建任务。
- 确认前端展示总览、文件、函数、库函数、全局函数库、模型、论文空状态、图示、报告。
- 确认后端 `http://127.0.0.1:8000/health` 正常。

## 12. 版本发布检查清单

- 版本号全部为 `1.0.0`。
- README 能让新读者 10 分钟内启动项目。
- docs 能支持 GitHub 展示、简历描述和面试讲解。
- 一键启动脚本可用。
- 一键验收脚本可用。
- 后端测试通过。
- 前端测试和构建通过。
- 没有提交本地数据库、缓存、`node_modules`、`dist`、任务输出。
- 明确声明 v1.0 不包含登录、复杂部署、PDF 导出、RAG 增强和人工编辑知识库。
- 保持现有分析主流程稳定。

## 13. 可能风险和解决方案

风险：一键启动依赖用户本机 Conda 环境名称。  
解决方案：README 明确默认环境名为 `code-research-agent`，手动启动命令作为 fallback。

风险：文档过长，新读者找不到入口。  
解决方案：README 只保留入口级内容，细节拆到 docs。

风险：截图资产暂时缺失。  
解决方案：提供 `docs/screenshots.md` 截图清单和采集说明，后续补图。

风险：验收脚本执行时间较长。  
解决方案：脚本只做明确的测试和构建，不做额外数据生成。

风险：运行时产物被误提交。  
解决方案：`.gitignore` 覆盖缓存、SQLite、`outputs/task_*`、`node_modules`、`dist`，并在 docs 中写清理命令。

## 14. 执行顺序

1. 创建 `plan/plan_stage10.md`。
2. 更新版本号到 `1.0.0`。
3. 新增 `scripts/dev.sh`。
4. 新增 `scripts/validate.sh`。
5. 重写 README 为 GitHub 首页级结构。
6. 新增 docs 文档集。
7. 确认 `.gitignore` 覆盖运行时产物和构建产物。
8. 执行脚本语法检查。
9. 执行后端测试。
10. 执行前端依赖安装、测试和构建。
11. 清理缓存、构建产物、本地 SQLite 和任务输出。
12. 最终检查版本号、文件状态和交付说明。
