# v0.9 开发计划：全局 Python 函数库页面

## 1. 阶段目标

v0.9 基于 v0.8.1 已有的全局 Python 函数知识库 SQLite 能力，把后台沉淀的库函数解释变成前端可见、可检索、可演示的学习知识库页面。

目标能力：

- 后端提供全局函数库查询 API。
- 前端新增“全局函数库”页面 / tab。
- 用户可以查看所有已沉淀的 Python / PyTorch / NumPy / PIL / OpenCV / einops 等库函数。
- 支持按函数名搜索。
- 支持按 `package_name`、`category`、`confidence` 筛选。
- 支持查看函数详情。
- 支持查看函数出现历史。
- 支持查看高频函数。
- 支持查看低置信度函数。
- 保持现有分析主流程不变。

## 2. 本阶段不做什么

v0.9 不做：

- 不实现用户登录系统。
- 不实现人工编辑库函数解释。
- 不实现删除、收藏、标注、审核工作流。
- 不实现 PDF 导出。
- 不实现 Graphviz / PNG / SVG 导出。
- 不实现复杂 RAG。
- 不实现官方文档在线检索。
- 不重构 LangGraph 分析主流程。
- 不改变库函数知识生成逻辑。
- 不改变分析任务输出结构。
- 不把前端“当前任务库函数说明”替换掉；v0.9 是新增全局查看能力。

## 3. 当前后端函数库能力检查

当前已有能力：

- `LibraryFunctionService` 使用 SQLite 存储全局库函数解释。
- 默认数据库路径为 `data/python_function_library.sqlite3`。
- 可通过 `LIBRARY_DB_PATH` 或 `run_analysis(..., library_db_path=...)` 覆盖。
- 已有表：`library_functions`、`library_function_occurrences`。
- 已有基础 service 方法：`get_by_canonical_name()`、`list_functions()`、`list_occurrences()`。

当前缺口：

- 没有 FastAPI 全局函数库 API。
- 列表查询不支持搜索、category、confidence、offset、排序。
- 没有统计接口。
- 没有高频函数接口。
- 没有低置信度函数接口。
- 前端没有全局函数库页面。

## 4. 需要新增或调整的后端 API

在 `backend/app/main.py` 中新增 MVP API，不拆分路由文件，保持 v0.8 结构简单。

新增 API：

```text
GET /library/functions
GET /library/functions/{canonical_name}
GET /library/functions/{canonical_name}/occurrences
GET /library/stats
GET /library/functions/high-frequency
GET /library/functions/low-confidence
```

`GET /library/functions` 支持 `query`、`package_name`、`category`、`confidence`、`limit`、`offset`、`sort`、`library_db_path`。返回 `items`、`total`、分页信息和可用筛选项。

`GET /library/functions/{canonical_name}` 返回完整函数详情、出现次数、首次出现和最近出现时间。

`GET /library/functions/{canonical_name}/occurrences` 返回函数出现历史，支持分页。

`GET /library/stats` 返回函数总数、出现总数、包分布、类别分布和置信度分布。

`GET /library/functions/high-frequency` 返回按出现次数排序的函数摘要。

`GET /library/functions/low-confidence` 返回低置信度函数列表；为空时返回空列表。

## 5. 前端页面设计

在 v0.8 工作台中新增主 tab：

```text
全局函数库
```

位置：

```text
总览 / 文件 / 函数 / 库函数 / 全局函数库 / 模型 / 论文 / 图示 / 报告
```

页面布局：

- 顶部：统计卡片。
- 搜索和筛选区：搜索框、package/category/confidence/sort 下拉、清空筛选。
- 主区域：函数列表。
- 详情区域：函数教学解释和出现历史。
- 侧边区域：高频函数、低置信度函数。

页面只做查看，不做编辑。

## 6. 全局函数库列表设计

列表字段：

- 函数名：`canonical_name`
- 包：`package_name`
- 类别：`category`
- 置信度：`confidence`
- 一句话作用：`summary`
- 出现次数：`occurrence_count`
- 更新时间：`updated_at`

交互：

- 点击列表项打开详情。
- 空库时显示：`暂无全局函数库记录，请先运行一次代码分析任务。`
- 加载中显示统一 loading 状态。
- API 错误显示 `ErrorBanner`。

## 7. 搜索和筛选设计

搜索：

- 输入框 placeholder：`搜索 torch.randn / Linear / numpy...`
- 点击搜索按钮或回车触发。
- v0.9 不做实时防抖搜索。

筛选：

- `package_name` 下拉。
- `category` 下拉。
- `confidence` 下拉。
- 排序下拉：函数名、最近更新、出现次数。

筛选来源：

- 使用 `/library/functions` 返回的 `filters`。

重置：

- 提供“清空筛选”按钮。
- 清空后重新请求第一页。

## 8. 函数详情页 / 详情弹窗设计

复用 v0.8 的教学解释展示风格，但数据来自全局 API。

详情展示：

- `canonical_name`
- `display_name`
- `package_name`
- `category`
- `confidence`
- `source_type`
- `summary`
- `beginner_explanation`
- `parameters_explanation`
- `return_explanation`
- `common_usage`
- `code_example`
- `shape_or_tensor_note`
- `common_mistakes`
- `related_functions`
- `official_doc_url`
- `created_at`
- `updated_at`
- `occurrence_count`

v0.9 不支持编辑字段。

## 9. 函数出现历史设计

出现历史从 `/library/functions/{canonical_name}/occurrences` 获取。

展示字段：

- 任务 ID
- 项目名
- 文件路径
- 函数名 / 方法名
- 行号
- 调用文本
- 记录时间

默认展示最近 50 条；无历史时显示：`暂无出现历史。`

## 10. 高频函数展示设计

高频函数来自 `/library/functions/high-frequency`。

展示：

- `canonical_name`
- `occurrence_count`
- `package_name`
- `category`

点击高频函数可打开详情。

## 11. 低置信度函数展示设计

低置信度函数来自 `/library/functions/low-confidence`。

展示：

- `canonical_name`
- `summary`
- `package_name`
- `category`
- `confidence`
- `occurrence_count`

如果为空，显示：`暂无低置信度函数。`

## 12. 前端组件拆分

新增组件：

```text
frontend/src/components/GlobalLibraryPanel.tsx
frontend/src/components/GlobalLibraryFilters.tsx
frontend/src/components/GlobalLibraryList.tsx
frontend/src/components/GlobalLibraryDetail.tsx
frontend/src/components/FunctionOccurrenceList.tsx
frontend/src/components/HighFrequencyFunctions.tsx
frontend/src/components/LowConfidenceFunctions.tsx
```

修改组件：

```text
frontend/src/components/ResultTabs.tsx
frontend/src/App.tsx
```

## 13. 前端数据流设计

新增 API client 方法：

```ts
listGlobalLibraryFunctions(params)
getGlobalLibraryFunction(canonicalName)
getGlobalLibraryOccurrences(canonicalName, params)
getGlobalLibraryStats()
getHighFrequencyFunctions(limit)
getLowConfidenceFunctions(limit)
```

页面数据流：

1. 用户打开“全局函数库”tab。
2. 前端并行请求 stats、函数列表、高频函数、低置信度函数。
3. 用户搜索或筛选时重新请求函数列表。
4. 用户点击某个函数时请求函数详情和出现历史。
5. 请求失败时保留页面结构，并显示错误状态。

## 14. TypeScript 类型设计

新增全局函数库类型：

- `GlobalLibraryFunction`
- `LibraryFunctionOccurrence`
- `GlobalLibraryListResponse`
- `GlobalLibraryStats`
- `GlobalLibraryDetailResponse`
- `LibraryOccurrencesResponse`

这些类型复用 `LibraryFunctionDoc` 字段，并增加 `occurrence_count`、分页和统计结构。

## 15. 错误和空状态设计

后端：

- 数据库不存在时自动 `ensure_schema()`，返回空结果。
- 参数非法返回 400。
- 函数不存在返回 404。
- SQLite 读取错误返回 500，并带简短 detail。

前端：

- 全局函数库为空：显示空状态和“先运行分析任务”的提示。
- 搜索无结果：显示“没有匹配的函数”。
- 详情加载失败：详情区域显示错误，不影响列表。
- 出现历史为空：显示空状态。
- 高频函数为空：显示空状态。
- 低置信度函数为空：显示空状态。

## 16. 测试计划

后端新增测试：

```text
tests/test_library_api.py
```

覆盖全局函数列表、搜索、筛选、分页、详情、出现历史、统计、高频函数和低置信度函数。

服务层测试扩展：

```text
tests/test_library_function_service.py
```

覆盖搜索、详情统计、出现历史分页、全局统计、高频函数和低置信度函数。

前端测试新增：

```text
frontend/src/__tests__/GlobalLibraryPanel.test.tsx
frontend/src/__tests__/GlobalLibraryDetail.test.tsx
```

覆盖页面加载、列表展示、搜索筛选、详情、出现历史、高频函数、低置信度空状态和错误状态。

回归测试：

```bash
pytest -q
cd frontend && npm ci && npm test && npm run build
```

## 17. 验收标准

v0.9 完成后必须满足：

- 版本号更新为 `0.9.0`。
- 不修改 LangGraph 分析主流程。
- 后端提供全局函数库 API。
- 前端新增“全局函数库”页面。
- 页面能展示所有已入库函数。
- 页面支持搜索。
- 页面支持按 package 筛选。
- 页面支持按 category 筛选。
- 页面支持按 confidence 筛选。
- 页面能展示函数详情。
- 页面能展示函数出现历史。
- 页面能展示高频函数。
- 页面能展示低置信度函数。
- 当前任务“库函数”tab 仍可用。
- 零基础模式库函数弹窗仍可用。
- `pytest -q` 通过。
- `cd frontend && npm ci && npm test && npm run build` 通过。
- 不实现登录、人工编辑、PDF 导出、复杂 RAG、官方文档在线检索。

## 18. 可能风险和解决方案

风险：SQLite 数据库为空，页面像坏掉。  
解决方案：后端返回空列表和 0 统计；前端显示明确空状态。

风险：`canonical_name` 包含特殊字符导致 URL 问题。  
解决方案：前端使用 `encodeURIComponent`；后端依赖 FastAPI path decode。

风险：全局函数过多导致列表过重。  
解决方案：后端限制 `limit <= 200`，前端使用分页。

风险：低置信度函数当前很少或没有。  
解决方案：允许空状态；不把 skipped unknown calls 强行写入数据库。

风险：误解为可编辑知识库。  
解决方案：页面文案明确 v0.9 仅查看和检索，人工编辑留后续版本。

## 19. 执行顺序

1. 更新版本到 `0.9.0`。
2. 创建 `plan/plan_stage9.md`。
3. 扩展 `LibraryFunctionService`。
4. 新增 `/library/*` API。
5. 新增后端 API 测试。
6. 扩展服务层测试。
7. 扩展前端类型和 API client。
8. 新增全局函数库组件。
9. 修改 `ResultTabs.tsx`，加入“全局函数库”tab。
10. 调整 `App.tsx`，让全局库页面可在无任务结果时访问。
11. 新增前端测试。
12. 更新 README。
13. 运行后端、前端测试和构建。
14. 清理缓存和构建产物。
