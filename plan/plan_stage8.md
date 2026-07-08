# v0.8 开发计划：前端正常模式 / 零基础模式 MVP

## 1. 阶段目标

v0.8 将当前后端分析工具升级为可交互产品原型：用户可以通过浏览器创建分析任务、查看结构化分析结果，并在“正常模式 / 零基础模式”之间切换。零基础模式聚焦函数详情中的 `library_calls`，点击库函数名后弹出教学级解释。

必须展示：

- 项目总览
- 文件级分析
- 函数级分析
- Python 库函数说明
- 模型网络结构分析
- 论文解析与论文代码对齐
- 图示分析

## 2. 本阶段不做什么

- 不实现全局函数库管理页面，留到 v0.9。
- 不实现 PDF 导出。
- 不实现 Graphviz / PNG / SVG 导出。
- 不实现复杂登录系统。
- 不实现复杂 RAG。
- 不实现论文图表解析。
- 不重构稳定的后端 LangGraph 分析流程。
- 不做异步任务队列；v0.8 仍同步等待分析完成。

## 3. 推荐前端技术栈

选择 React + Vite + TypeScript。

理由：

- 当前项目是 FastAPI 后端，React + Vite 适合作为轻量独立前端。
- Vite 配置少、启动快，适合 MVP。
- TypeScript 能约束后端 JSON 结果结构。
- 通过 Vite proxy 访问 FastAPI，降低 CORS 和部署复杂度。
- Mermaid 可用 `mermaid` npm 包基础渲染，失败时回退代码块。

## 4. 前端目录结构设计

新增：

```text
frontend/
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    api/client.ts
    types/analysis.ts
    styles.css
    components/
      AppShell.tsx
      TaskForm.tsx
      ModeToggle.tsx
      SummaryCards.tsx
      ResultTabs.tsx
      FileAnalysisPanel.tsx
      FunctionAnalysisPanel.tsx
      FunctionDetail.tsx
      LibraryCallChip.tsx
      LibraryFunctionModal.tsx
      LibraryDocsPanel.tsx
      ModelAnalysisPanel.tsx
      PaperAnalysisPanel.tsx
      DiagramsPanel.tsx
      MermaidBlock.tsx
      EmptyState.tsx
      LoadingState.tsx
      ErrorBanner.tsx
    __tests__/
      App.test.tsx
      LibraryFunctionModal.test.tsx
      FunctionDetail.test.tsx
```

## 5. 后端 API 现状检查

当前已有：

```text
GET /health
POST /analysis/tasks
```

缺口：

- 浏览器不能直接读取本地 JSON 文件路径。
- 缺少按 `task_id` 获取完整分析结果的 API。
- 缺少任务列表 API。
- 缺少浏览器文件上传 API。

## 6. 需要新增或调整的 API

新增：

```text
GET /analysis/tasks
GET /analysis/tasks/{task_id}
GET /analysis/tasks/{task_id}/report
POST /analysis/tasks/upload
```

规则：

- `task_id` 只允许 `task_[A-Za-z0-9]+`。
- 结果读取只访问 `outputs/{task_id}`。
- 缺失文件返回空结构并记录 errors。
- 上传文件保存到 `outputs/_uploads/{request_id}/` 后调用现有 `run_analysis()`。
- ZIP 必须 `.zip`，论文必须 `.pdf`。
- 新增 `python-multipart` 依赖。

## 7. 页面设计

页面是工作台，不做营销页：

- 顶部栏：项目名 + 模式切换。
- 左侧：任务创建表单、最近任务。
- 主区域：结果 tabs。
- 弹窗：库函数教学解释。

Tabs：

```text
总览 / 文件 / 函数 / 库函数 / 模型 / 论文 / 图示 / 报告
```

## 8. 正常模式设计

正常模式用于快速浏览结构化结果：

- 总览展示计数指标。
- 文件页按文件卡片展示类型、作用、主要类和函数。
- 函数页展示函数列表和详情。
- 库函数页展示当前任务库函数说明。
- 模型页展示 layers、forward steps、组件候选。
- 论文页展示标题、摘要、贡献和对齐。
- 图示页展示 Mermaid 渲染或代码块。
- 报告页展示 `report.md`。

## 9. 零基础模式设计

零基础模式不重新请求后端，只改变前端展示。

函数详情必须突出：

- `beginner_explanation`
- `library_calls`
- 库函数教学解释入口
- shape / tensor 注意事项
- common mistakes

低置信 unknown 调用弱化展示，不当作确认库函数。

## 10. 库函数弹窗设计

点击 `LibraryCallChip` 打开 `LibraryFunctionModal`。

匹配规则：

- 用 `library_function_docs.library_function_docs` 建 `canonical_name -> doc` map。
- 找不到 doc 时展示 fallback。

展示字段：

- summary
- beginner_explanation
- parameters_explanation
- return_explanation
- common_usage
- code_example
- shape_or_tensor_note
- common_mistakes
- related_functions
- confidence

## 11. Mermaid 图展示方案

使用 `mermaid` npm 包做基础渲染：

- 成功时展示 SVG。
- 失败时展示 Mermaid 代码块。
- 不做 PNG / SVG 文件导出。
- 不做缩放、拖拽、复杂交互。

## 12. 前端数据流设计

核心 API：

```text
createTaskByPath(payload)
createTaskByUpload(formData)
listTasks()
getTaskResult(taskId)
getTaskReport(taskId)
```

数据流：

1. 用户创建任务。
2. 后端返回 summary。
3. 前端根据 `task_id` 拉取完整结果。
4. Tabs 根据结构化 JSON 渲染。
5. 点击函数选择详情。
6. 点击库函数打开弹窗。

## 13. 组件拆分设计

核心组件：

- `AppShell`
- `TaskForm`
- `ModeToggle`
- `SummaryCards`
- `ResultTabs`
- `FileAnalysisPanel`
- `FunctionAnalysisPanel`
- `FunctionDetail`
- `LibraryCallChip`
- `LibraryFunctionModal`
- `LibraryDocsPanel`
- `ModelAnalysisPanel`
- `PaperAnalysisPanel`
- `DiagramsPanel`
- `MermaidBlock`
- `EmptyState`
- `LoadingState`
- `ErrorBanner`

## 14. 错误和加载状态设计

- 创建任务时显示 loading 并禁用提交按钮。
- 创建失败显示后端错误。
- 结果文件缺失时保留页面，模块显示空状态。
- Mermaid 渲染失败时回退代码块。
- 库函数 doc 缺失时弹窗展示调用信息。
- 上传格式前后端都校验。

## 15. 测试计划

后端：

- 保持 JSON 路径创建任务兼容。
- 测试任务列表。
- 测试完整任务结果读取。
- 测试报告读取。
- 测试非法 task_id。
- 测试缺失文件容错。
- 测试 multipart 上传 ZIP/PDF。
- 测试错误文件类型拒绝。

前端：

- `App` 基础渲染。
- `FunctionDetail` 正常 / 零基础模式。
- `LibraryFunctionModal` 有 doc 和无 doc。
- low confidence unknown 调用弱化显示。
- `npm run build` 通过。
- `npm test` 通过。

## 16. 验收标准

- 版本号为 `0.8.0`。
- 前端可启动。
- 浏览器能创建分析任务。
- 浏览器能读取并展示任务结果。
- 支持正常模式 / 零基础模式切换。
- 零基础模式函数详情显示 `library_calls`。
- 点击库函数名弹出教学级解释。
- Mermaid 图能渲染或回退代码块。
- 原有 CLI 和 API 流程保持可用。
- 后端 pytest 全部通过。
- 前端 test/build 通过。
- 不实现全局函数库管理、PDF 导出、Graphviz/PNG/SVG 导出、复杂登录。

## 17. 可能风险和解决方案

- 浏览器不能读本地 JSON：由后端新增结果 API。
- 上传接口影响分析流程：上传只保存文件并调用现有 `run_analysis()`。
- 同步分析等待较久：v0.8 用 loading 状态处理。
- JSON 类型多：前端使用宽松 TypeScript 类型，只覆盖展示字段。
- 库函数说明匹配失败：弹窗 fallback。
- Mermaid 渲染失败：展示源码。
- 页面信息过载：使用 tabs 和详情面板。

## 18. 执行顺序

1. 更新版本到 `0.8.0`。
2. 新增后端任务列表、结果读取、报告读取和上传 API。
3. 新增 `python-multipart` 依赖。
4. 创建 React + Vite + TypeScript 前端。
5. 实现 API client 和类型。
6. 实现任务创建、最近任务、模式切换和结果 tabs。
7. 实现各结果面板。
8. 实现零基础模式函数详情和库函数弹窗。
9. 实现 MermaidBlock。
10. 新增后端 API 测试。
11. 新增前端组件测试。
12. 更新 README。
13. 运行后端 pytest。
14. 运行前端 test/build。
15. 清理缓存和构建产物。
