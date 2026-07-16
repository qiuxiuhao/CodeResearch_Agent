# v1.3.5 全仓代码审计与轻量化计划

基线提交：`ce4f1ee`。本轮以保留全部有效功能、安全边界和 fallback 为前提，删除确定不可达代码、统一配置入口并降低维护复杂度；文件数、行数和 ZIP 大小仅记录，不驱动删除。

## 1. 稳定基线与不可退化边界

| 指标 | v1.3.4 基线 |
|---|---:|
| Python 文件 | 177 |
| TypeScript/TSX 源文件 | 54 |
| 代码行数 | 25,053 |
| 直接运行时依赖 | 后端 7、前端 6 |
| 前端构建产物 | 3,684,247 B |
| 首屏主 JS | 885.63 kB，gzip 230.85 kB |
| 后端测试 | 179 passed，43.36s |
| 前端测试 | 26 passed，1.29s |
| 后端启动 import 中位数 | 0.2451s |
| Git 跟踪文件 ZIP | 470,723 B |

必须保留 FastAPI 动态路由、LangGraph 21 个 Node 和顺序 fallback、纯规则离线路径、Blueprint fallback、Mermaid、Provider fallback、SSRF/Secret/Origin/授权隔离、缓存 hash/schema 校验、Mock Provider、正常模式和零基础模式。旧公开入口保留一个弃用版本，v1.4 再删除。

## 2. 删除前引用检查与证据格式

每个候选必须检查 Python AST、`__init__.py` re-export、`__all__`、CLI entry point、`__main__`、FastAPI/OpenAPI/Pydantic、LangGraph Node/edge/fallback、`importlib`/`__import__`/字符串动态导入、pytest monkeypatch/patch 字符串路径、前端 barrel/re-export/`React.lazy`/`import()`/Mock，以及文档、示例、缓存反序列化和历史任务字段。

删除记录必须包含：路径、符号或范围、当前作用、无用判断、静态证据、动态/反射风险、风险等级、操作、需修改调用方和回归测试。`tests/test_public_import_contract.py` 固定公开包入口、Provider `__all__`、Mock Provider 和关键 OpenAPI 路由；内部删除符号列入排除清单。

## 3. 确定性候选

### A01–A11（批次 1）

| ID | 路径与符号 | 依据 | 操作与回归 |
|---|---|---|---|
| A01 | `llm/budget.py:asdict`、Teaching Diagram 测试的 `json` | 无 Load 引用 | 删除 import；专项测试 |
| A02 | 三个 Provider config 的六个 `*_source` 变量 | 赋值后未读取 | 改为 `_`；Provider settings 测试 |
| A03 | `EvidenceValidationError` | 无 import、raise、except 或公开导出 | 删除；LLM evidence/router 测试 |
| A04 | `normalize_image_bytes_to_png` | 零调用；活动路径使用 `write_validated_image()` | 删除；图片安全测试 |
| A05 | `is_too_large` | 零调用；活动安全读取承担限制 | 删除；上传/repo scan 测试 |
| A06 | `storage_service.task_output_dir` | 零调用；活动实现含路径穿越检查 | 删除；API result 测试 |
| A07 | `_validate_external_model_consent` | 零调用；已有完整授权解析 | 删除；consent 测试 |
| A08 | `FileTreeNode` | 仅定义和自引用，RepoIndex 未使用 | 删除；Pydantic/repo scan 测试 |
| A09 | `AIStatusBanner.tsx` | 无 import 或挂载 | 删除；Dashboard/LLM panel 测试 |
| A10 | 前端同步创建包装器、`getTaskReport` | 前端零调用 | 删除前端函数，保留后端路由 |
| A11 | `SummaryCards.tsx` | 仅转发 Dashboard | ResultTabs 直接挂载 Dashboard |

批次 1 严格只处理 A01–A11，不包含 Prompt、A12、A13、A15、Provider 或 Runtime 重构。

### A12（批次 2）

删除构建生成物 `frontend/vite.config.js`、`frontend/vite.config.d.ts`、`frontend/tsconfig.tsbuildinfo`、`frontend/tsconfig.node.tsbuildinfo`。新增 app/node 两套 no-emit typecheck；禁止 `tsc -b`，连续两次 build 后工作树为空且根目录无上述文件或任何 `*.tsbuildinfo`。

### A13（批次 7）

`examples/small_pytorch_project/` 保留为唯一事实源，提交 ZIP 继续供演示。测试在 `tmp_path` 中按固定路径顺序、时间戳、权限和压缩参数生成 ZIP，并验证源码与提交 ZIP 的路径集合和逐文件 SHA-256 一致。

### A14（批次 1.5）

先建立稳定 task key 到实际 Prompt 文件的显式 Registry，覆盖文件、函数、模型、论文对齐和 Figure VLM；Node 不再散落裸文件名，Narrative 内联 Prompt 不纳入目录 Registry。契约测试验证文件存在、唯一、Registry 与目录 `.md` 一一对应，并验证不可信输入、禁止执行和严格 JSON 约束。完成后删除七个确认未使用的旧规则/占位 Prompt并同步文档。

### A15（批次 5）

删除 `ImageGenerationSettings.task_*`、全部 `IMAGE_TASK_*`、Provider 异步 runtime 分支与 `self.supports_async`、registry/持久化/public settings/前端中的异步配置。公开请求字段 `ProviderSettingsUpdateRequest.supports_async` 与 `ProviderValidateRequest.supports_async` 保留一版并标记 `deprecated=True`：未传或 false 接受但不持久化、不进 runtime，true 返回 422，旧 Secret Store 值忽略，v1.4 删除。

## 4. TypeScript no-emit 与 Mermaid

新增 `frontend/tsconfig.typecheck.json` 继承 app 配置，设置 `noEmit: true`、`incremental: false`、清空 references 且只含 `src/`；node 配置移除 composite，设置 noEmit/incremental=false，仅检查 `vite.config.ts`。`typecheck` 分别执行两个 `tsc -p ... --noEmit`，`build` 先 typecheck 再 Vite。build 不得生成配置 JS、d.ts 或 tsbuildinfo。

业务页面可 `React.lazy`，Mermaid 普通模块必须在 `MermaidBlock` 内 `await import("mermaid")`，禁止把 Mermaid 本身作为 lazy React 组件。仅在图示挂载后加载；每个异步边界检查 cancelled/disposed，卸载后不得 setState 或写 DOM，使用唯一 render ID 防止迟到覆盖。import/render 失败显示源码 fallback。构建 manifest 证明 entry 静态闭包不含 Mermaid、dynamic imports 含 Mermaid chunk；总大小增长超过 10% warning，超过 20% 且无解释时阻塞。

## 5. Provider 与重复代码合并

B01–B05 每项独立提交、验收、revert；不创建大一统 `BaseRouter`，只抽取语义完全一致的纯 helper。Provider 请求格式、缓存、安全和异常语义保持独立。实施前后记录 LOC、条件分支和重复块，净代码量和复杂度不下降则撤销抽象。

| ID | 范围 | 允许合并 | 禁止合并 |
|---|---|---|---|
| B01 | Provider config/设置服务 | 字段定义、来源优先级、纯类型转换 | Provider 请求、Runtime、Secret/SSRF |
| B02 | main/analysis service | 授权和开关解析 | Provider、Router、HTTP Client |
| B03 | 三个 Router | attempt 序号、预算 reservation、标准 warning 字段 | cache key、下载、Schema、异常类 |
| B04 | LLM/Vision HTTP Provider | JSON 对象提取、optional usage int、安全错误摘要 | 请求体和 Provider capability |
| B05 | AI usage | 归一化后的五组统计构建 | 历史读取和缓存兼容 |

`ResolvedAnalysisOptions` 必须是可 JSON round-trip 的纯数据，不含 API Key、Secret Store、Provider、Router、HTTP Client、callable 或任意对象；提供显式 public/state dump。`ProviderRuntimeContext` 单独留在进程内，不进入 AgentState、任务 JSON、报告、缓存、progress 或日志，也不提供公共序列化路径。测试递归检查任务产物和错误信息不含测试 Secret。

## 6. Narrative Schema（批次 6）

删除 `plain_language_explanations`、`layout_suggestions`、`color_suggestions`、`metadata`，同时固定：

```text
NARRATIVE_PROMPT_VERSION = "1.3.5"
NARRATIVE_SCHEMA_VERSION = "1.3.5"
NARRATIVE_CACHE_VERSION = "1.3.5"
```

`TeachingDiagramNarrative` 增加受控 `schema_version`；system prompt、allowed fields、本地 builder、Router payload 与 cache key 同步。预置旧 v1.3.3 Narrative 缓存必须 miss 并写新缓存。不修改 TeachingDiagramSpec、Blueprint、Image Generation、Review 或 Vision Schema。

## 7. 版本、提交与回滚

实施前创建 annotated tag `v1.3.4-stable -> ce4f1ee`；已有标签只能验证，不得移动。每批至少一个独立提交，批次 1.5 独立，B01–B05 各自独立，提交信息带批次号。失败只 `git revert` 当前批次，禁止重写历史。

全部通过后单独 `chore(release): v1.3.5`，统一更新 `pyproject.toml`、前端 package/lock 根版本、FastAPI、README、API/validation/architecture 和 release/plan 索引。Narrative 版本仅在批次 6 更新，其他缓存与 Blueprint/Image Schema 不随应用版本改号。最终创建 `v1.3.5` tag。

## 8. 实施顺序

1. 批次 0：稳定基线、tag、指标、核心能力矩阵、公开 import 契约。
2. 批次 1：只处理 A01–A11。
3. 批次 1.5：Prompt Registry 与 A14。
4. 批次 2：A12 no-emit、Mermaid 动态加载、Vite 构建依赖轻量化。
5. 批次 3：只实施 B01 Provider 配置事实源。
6. 批次 4：依次 B02、B03、B04、B05，每项独立提交；不满足复杂度门槛即撤销。
7. 批次 5：A15 与旧兼容入口弃用；前端停止发送旧授权字段。
8. 批次 6：Narrative Schema 清理和旧缓存失效。
9. 批次 7：确定性示例 ZIP、历史计划归档、README/docs/`.env.example` 同步。
10. 最终版本批次：统一升 1.3.5、最终测试/性能/安全、tag。

## 9. 核心能力验收矩阵

| 能力 | 必须覆盖 |
|---|---|
| 纯规则离线分析 | 无 Key、无网络完成 ZIP 分析和报告 |
| LangGraph | 21 个 Node、顺序 fallback、进度和错误状态 |
| 正常/零基础模式 | 模式切换、库函数弹窗和教学解释 |
| Blueprint | 图片禁用、失败、Review 不通过时 fallback |
| Mermaid | 按需加载、卸载安全、渲染失败源码 fallback |
| Provider | retry、fallback、预算、缓存、错误语义 |
| Provider 设置 | UI > Environment > Default、Secret、revision |
| 安全 | SSRF、Origin、admin token、Secret 不落盘 |
| 授权隔离 | 文本、论文 VLM、图片、Review 相互独立 |
| 历史兼容 | 旧任务、旧字段、旧缓存安全读取 |
| Narrative | 本地/LLM/fallback、新版本和旧缓存 miss |
| 示例 | 源码生成 ZIP、提交 ZIP hash 一致 |
| FastAPI | 同步/异步、deprecated OpenAPI、上传限制 |
| 公开 import | `__init__`、`__all__`、Mock Provider 和文档入口 |
| 前端构建 | no-emit、动态 Mermaid、两次 build 无生成文件 |

## 10. 测试与性能

每批（含 1.5、B01–B05 子项和最终版本）均运行：

```bash
python -m pytest -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
bash scripts/validate.sh
```

测试数量只作参考；删除测试必须有等价参数化、契约或核心矩阵覆盖，安全/fallback/缓存/授权/离线路径覆盖不得降低；环境已有 pytest-cov 时可生成辅助 coverage。

完整 warm-up + 9 次中位数测量只在批次 0、批次 2、批次 3、批次 4 全部完成和最终验收执行。记录启动、核心离线样例、前端 build、全量测试；15%–25% 回退 warning 并重跑，两轮稳定超过 15% 或单轮超过 25% 才阻塞。纯 import 删除和文档整理不重复九次测量。

## 11. 最终验收

- A01–A11、A12、A14、A15 位于指定批次且动态引用检查完整。
- 无新的大一统 Router；B01–B05 的净代码与复杂度门槛成立。
- options 可安全序列化且不含 Secret/runtime；runtime context 仅在进程内。
- no-emit build 无配置 JS、声明或 tsbuildinfo；连续两次 build 后工作树为空。
- Mermaid 不在首屏静态依赖，卸载后不更新状态/DOM，失败显示源码。
- `supports_async` 保留一版弃用语义且 true 返回 422。
- Narrative 旧缓存确定性失效，其他 Schema 不变。
- 展开示例与提交 ZIP 内容一致。
- 各批次提交可独立 revert，最终统一升至 1.3.5 并通过矩阵、测试和性能规则。
