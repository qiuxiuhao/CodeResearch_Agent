# 简历描述

## 短版

CodeResearch Agent：基于 FastAPI + LangGraph + React 构建的深度学习代码理解工具，支持 AST 仓库分析、函数/模型结构提取、论文代码对齐、Mermaid 图示，以及 SQLite 全局 Python 函数知识库。

## 长版

- 设计并实现 LangGraph 工作流，将 ZIP 仓库和可选论文 PDF 转换成结构化 JSON、Markdown 报告和前端页面。
- 基于 Python AST 实现确定性解析，提取 import、alias、类、函数、方法、库函数调用和 PyTorch 风格模型结构。
- 构建 SQLite 全局知识库，沉淀 Python / PyTorch / NumPy 函数教学解释，支持搜索、筛选、详情查看、低置信度函数查看和零基础解释复用。
- 实现 MVP 论文解析和启发式论文代码对齐，并为对齐结果提供 confidence 和 evidence。
- 生成项目结构、模型流程、核心模块、函数逻辑和论文代码对齐 Mermaid 图。
- 构建 React + Vite 前端，支持正常模式、零基础模式和库函数教学解释弹窗。

## 技术关键词

FastAPI、LangGraph、Python AST、Pydantic、SQLite、PyMuPDF、Mermaid、React、Vite、TypeScript、静态分析、代码智能、深度学习工具链。

## 面试切入点

这个项目适合面试讲解，因为它不只是前端 demo，也不是简单 prompt 包装器。它有真实的分析流水线、持久化知识库、结构化产物、测试覆盖和明确的工程取舍。
