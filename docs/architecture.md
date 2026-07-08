# 架构说明

CodeResearch Agent 是一个本地优先的代码理解系统，面向深度学习代码仓库和可选论文 PDF。v1.0 保持确定性的分析流程，并通过 JSON 文件、Markdown 报告和 React 前端展示结果。

## 分层结构

- FastAPI API 层：负责任务创建、文件上传、结果读取、报告读取和全局函数库查询。
- LangGraph 工作流层：编排仓库解压、解析、分析、文档生成、图生成和报告生成。
- Tool 工具层：提供确定性的静态分析工具，包括仓库扫描、AST 解析、模型识别、论文解析、论文代码对齐、Mermaid 生成和报告构建。
- Service 服务层：`analysis_service` 负责单次分析任务编排，`library_function_service` 管理 SQLite 全局 Python 函数知识库。
- Schema 数据层：使用 Pydantic 定义仓库、文件、函数、模型、论文、图示和库函数等稳定 JSON 结构。
- Frontend 前端层：React + Vite 工作台，支持任务创建、结果浏览、零基础解释、图示展示和全局函数库检索。

## 数据流

1. 用户提供 ZIP 文件路径，或通过浏览器上传 ZIP。
2. 用户可以可选提供论文 PDF。
3. 后端创建任务，并把 ZIP 解压到 `outputs/{task_id}/source`。
4. LangGraph 节点生成结构化 JSON 产物。
5. 报告节点写入 `report.md`。
6. API 从 `outputs/{task_id}` 读取任务产物。
7. 前端在总览、文件、函数、库函数、模型、论文、图示和报告页面中展示结果。
8. 库函数解释持久化到 SQLite，并可在全局函数库页面中检索。

## 运行时产物

项目有意不提交生成数据：

- `outputs/task_*`
- `data/*.sqlite3`
- `frontend/node_modules`
- `frontend/dist`
- Python 缓存和 egg-info 元数据

清理命令见 [验收说明](validation.md)。
