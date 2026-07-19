# v1.3.3 开发计划：稳定性修复 + 科技蓝前端与 Provider 设置中心

## 1. 当前问题分析

- 教学图 Review 仍复用论文 VLM 的 `external_vision_consent`，缺少独立的教学图审查外发授权；`external_vision_consent` 应只授权论文 Figure VLM，教学图 Review 必须使用独立 `external_teaching_review_consent`。
- 当 `image_generation_enabled=false` 但 `teaching_review_vlm_enabled=true` 时，当前语义容易被静默修正；v1.3.3 后端必须返回 `422`，不得悄悄改写请求。前端仍需在 UI 上自动关闭并禁用 Review，减少用户误操作。
- 教学文案 LLM 已在 v1.3.2 接入，但缺少 `teaching_narrative_llm_enabled` 独立开关；普通文本 LLM 和教学文案 LLM 不能分别启用。
- 前端只展示部分 AI 能力状态，未清晰拆分普通 LLM、教学文案、论文 VLM、图片生成、教学图 VLM Review 的预算、请求数、缓存命中。
- 当前生图实现仅支持同步请求；`IMAGE_TASK_*` / async 配置仍暴露在 `.env.example`，应隐藏或明确拒绝异步。
- `smoke_image.py` 只覆盖生图与合成，不覆盖 VLM Review 和 fallback。
- 前端视觉仍是浅色 MVP，和参考图的深色科技蓝仪表盘差距较大。
- Provider 配置仍主要依赖环境变量，没有 UI 设置中心、安全 Secret 存储、连接测试、配置来源展示、并发冲突检测和 Base URL SSRF 防护。

## 2. 总体架构

- 后端拆出 Provider Settings 子系统：Provider 配置读取统一走 `ProviderSettingsService`，并按字段合并，优先级固定为 `UI 字段 > Environment 字段 > Default 字段`。UI 只设置 `model` 时，不得覆盖环境变量中的 API Key、Base URL、timeout 等其他字段。
- Secret 存储拆为两层：优先 OS Keyring；不可用时使用仓库外权限受控 Secret Store，例如 `~/.coderesearch_agent/secrets.json`，文件权限 `0600`，目录权限 `0700`。
- 普通 LLM、教学文案 LLM、论文 VLM、图片生成、教学图 Review 保持独立 enabled / consent / budget / cache 展示。
- 新增任务级统一 `ai_usage`，包含 `text_analysis`、`teaching_narrative`、`paper_vision`、`image_generation`、`teaching_review`。`teaching_diagram_manifest` 不重复保存普通文本 LLM 的统计，只保存教学图自身产物、状态、fallback 和 review 摘要。
- 前端采用参考图方向的深色科技蓝主题，新增统一 CSS Variables Design Tokens，不在组件里散落硬编码颜色。
- Provider 设置中心采用“大型右侧抽屉”方案：不离开当前分析上下文，点击右上角设置按钮打开。
- v1.3.3 分两段实施：
  - `v1.3.3-a`：稳定性、授权开关、预算、smoke、测试。
  - `v1.3.3-b`：科技蓝前端、Provider 设置中心、安全配置 API。

## 3. v1.3.3-a 实施计划

- 后端开关与授权：
  - 新增 `teaching_narrative_llm_enabled`，允许在 `text_llm_enabled=false` 时单独启用教学文案 LLM。
  - 新增 `external_teaching_review_consent`，教学图 VLM Review 不再复用论文 `external_vision_consent`。
  - `external_vision_consent` 仅授权论文 Figure VLM；`external_teaching_review_consent` 仅授权教学图 Review；两者不得互相继承或替代。
  - 旧客户端未传 `external_teaching_review_consent` 时，教学图 Review 默认 disabled。
  - 当 `image_generation_enabled=false` 且 `teaching_review_vlm_enabled=true` 时，后端返回 `422`，不创建 Review Runtime 请求，不计预算，不静默修改请求体。
  - `teaching_review_vlm_enabled=true` 必须同时满足 `image_generation_enabled=true`、`external_image_consent=true`、`external_teaching_review_consent=true`。
- 预算与状态：
  - 任务 summary 新增统一 `ai_usage`，分组为 `text_analysis`、`teaching_narrative`、`paper_vision`、`image_generation`、`teaching_review`。
  - 每组统计 enabled、consent、provider、model、request_count、budget_limit、cache_hits、fallbacks、failures、warnings。
  - `teaching_diagram_manifest` 只保存教学图 spec、blueprint、raw/composite/final、review、fallback reason、diagram warnings，不重复保存普通文本 LLM 统计。
  - API summary 和前端总览分别展示 selected entities、provider requests、cache hits、fallbacks、failures。
- 同步生图约束：
  - 当前版本明确只支持同步生图；Provider `supports_async=true` 时后端返回配置 warning 并拒绝使用异步轮询。
  - `.env.example` 隐藏或标注 `IMAGE_TASK_*` 为“预留，v1.3.3 不启用”。
- `smoke_image.py --review`：
  - 增加 `--review` 参数，流程为 `生图 → Blueprint → Composite → VLM Review → pass/fallback`。
  - smoke 使用合成 TeachingDiagramSpec，不发送源码/论文。
  - 付费请求前打印 provider、model、request size、review provider、allowlist 和费用确认。
  - Review 不通过时必须展示 fallback Blueprint 路径和原因。
- 稳定性检查：
  - 检查 `httpx.Client`、PyMuPDF document/page/pixmap、SQLite connection、ThreadPoolExecutor 是否使用上下文管理或显式 close。
  - 增加资源释放回归测试，确保全量 pytest 正常退出。
- 补测：
  - SeedreamProvider MockTransport：请求结构、endpoint、错误映射、URL 下载、非兼容 Qwen 参数。
  - 图片生成关闭时 Review 请求返回 `422`、不执行、不计请求、不生成 final AI。
  - 教学文案 LLM 独立启用、普通文本 LLM 关闭仍可生成 narrative。
  - 普通文本 LLM 启用、教学文案 LLM 关闭时使用 local narrative。

## 4. v1.3.3-b 实施计划

- 科技蓝前端改版：
  - 新增 `frontend/src/theme/tokens.ts` 或 CSS token 区，定义颜色、阴影、边框、半径、字体、间距、状态色。
  - Design Tokens 必须通过 CSS Variables 暴露，例如 `--color-bg-app`、`--color-panel`、`--color-border-glow`、`--color-text-primary`、`--color-status-success`、`--shadow-glow-blue`。
  - 布局改为：顶部导航、右上模式切换与设置按钮、左侧任务创建面板、主内容科技蓝卡片区。
  - 总览页增加统计卡片、LLM/VLM/教学图状态条、快速入口、最近输出。
  - 小屏：左侧栏折叠为抽屉，顶部保留任务/设置入口。
  - 可访问性要求：文字对比度满足常用 WCAG AA 目标；键盘焦点清晰可见；状态表达不只依赖颜色，必须配合图标、文本或 aria label；动画遵守 `prefers-reduced-motion`。
- Provider 设置中心：
  - 采用右侧大型抽屉 `ProviderSettingsDrawer`。
  - 分组：文本 LLM（DeepSeek/Qwen）、视觉 VLM（Qwen-VL/GLM）、图片生成（Qwen-Image/Seedream）。
  - 每个 Provider 支持：enabled、API Key、Base URL、Model、Timeout、Retry、能力专属配置。
  - Qwen-Image/Seedream 展示 request width/height、结果域名 allowlist；VLM 展示 image/token 限制；LLM 展示 max output tokens / retry。
  - 保存后清空前端 API Key 输入框；只显示 `configured`、`masked_key`、`source`。
  - `masked_key` 默认只显示最后四位；短 Key 不显示任何片段；前端不得把 `masked_key` 当作真实 Key 回传。
  - Provider 设置带 `revision`；保存请求必须携带 `expected_revision`，冲突时展示 `409` 冲突提示并要求用户刷新或重新应用修改。
- 任务开关联动：
  - TaskForm 中普通文本 LLM、教学文案 LLM、论文 VLM、图片生成、教学图 Review 分开展示。
  - Review 开关依赖图片生成开关；图片生成关闭时 Review UI 自动 disabled 并显示原因。
  - 若通过旧页面状态、浏览器缓存或手写请求提交 `image_generation_enabled=false` 且 `teaching_review_vlm_enabled=true`，后端以 `422` 为准，前端显示可理解的错误。
  - 预算与授权区域展示普通 LLM、教学文案、论文 VLM、图片生成、教学图 Review 五类能力的独立预算和授权状态。

## 5. 后端 API 设计

新增安全 API：

```text
GET    /settings/providers
PUT    /settings/providers/{provider}
DELETE /settings/providers/{provider}/api-key
POST   /settings/providers/{provider}/validate
POST   /settings/providers/{provider}/test
```

- `GET /settings/providers` 返回：
  - provider id、display name、group、enabled、configured、masked_key、revision、base_url、model、timeout、retry、能力专属字段。
  - 非敏感字段必须返回字段级来源：`UI`、`Environment`、`Default`。
  - 不返回真实 API Key，不返回完整签名 URL，不返回原始供应商响应。
- `PUT /settings/providers/{provider}`：
  - 接收非敏感配置、可选 `api_key` 和必填 `expected_revision`。
  - `expected_revision` 与当前 revision 不一致时返回 `409`，不得部分保存。
  - `api_key` 只写 Secret Store，不写任务结果、日志、缓存或报告。
  - 空 `api_key` 表示不修改 Key；删除 Key 必须走 DELETE。
  - 前端不得把 `masked_key` 当作 `api_key` 回传；后端检测到 masked 格式时拒绝并返回 `422`。
- `DELETE /settings/providers/{provider}/api-key`：
  - 删除 UI 保存的 Key；环境变量 Key 不可删除，只返回 readonly 提示。
  - 请求也必须携带 `expected_revision`，冲突返回 `409`。
- `POST /settings/providers/{provider}/validate`：
  - 只做本地格式校验，不发外部请求，零费用。
  - 校验 provider id、model 格式、Base URL 格式、timeout/retry 范围、尺寸范围、allowlist 格式、是否需要高级自定义 endpoint 授权。
- `POST /settings/providers/{provider}/test`：
  - 必须请求体包含 `confirm_cost=true`。
  - 每次最多一个最小合成请求，不自动 fallback 到备用 Provider。
  - 不发送用户源码或真实论文。
  - 返回 success/failure、latency、sanitized warning，不返回原始响应、完整 URL 或 Key。
  - Provider test 使用与 Base URL 相同的 SSRF、HTTPS、重定向、超时和响应大小限制。
- Base URL 和 Provider test SSRF 防护：
  - 默认只允许官方 Provider 地址。
  - 自定义 endpoint 需要显式高级开关；本地模型 endpoint 需要独立显式授权。
  - 默认只允许 HTTPS，禁止 `file`、`ftp`、`gopher` 等协议。
  - 禁止 localhost、私网 IP、loopback、link-local、云元数据地址。
  - DNS 解析后校验 IP，重定向后重新校验。
  - 限制超时、响应大小和重定向次数。
- 安全访问：
  - 写接口默认仅允许 `127.0.0.1`、`::1`、`localhost`。
  - 默认不信任 `X-Forwarded-For`；仅配置可信代理时读取代理头。
  - 非本机访问必须配置管理员令牌，并校验 `Origin`。
  - 管理员令牌通过 Header 传递，后端使用常量时间比较。
  - 设置和 Provider test 接口增加速率限制。
  - 远程 Provider 配置写入默认关闭，必须显式启用。
  - 管理员令牌不得写入前端 bundle 或任务输出。

## 6. Secret 存储设计

- 禁止 API Key 保存到 `localStorage`、`sessionStorage`、`IndexedDB`、URL、任务 JSON、报告、缓存、日志或 Git。
- 前端只在受控 input state 中临时持有 Key；保存成功后立即清空。
- 后端 Secret Store：
  - 首选 `keyring`，service namespace 使用 `coderesearch-agent`。
  - fallback 文件位于仓库外，例如 `~/.coderesearch_agent/secrets.json`。
  - fallback 文件创建时强制权限 `0600`，目录 `0700`。
  - 文件 schema 包含 `schema_version`、`revision`、`providers`。
  - 保存流程必须使用并发锁、临时文件写入、`fsync` 文件、必要时 `fsync` 父目录、原子 `rename`。
  - 损坏文件、权限错误、写入失败必须安全回退并记录 sanitized warning；失败时不得向前端返回保存成功。
  - Secret value 加载后只进入 Provider runtime，不进入 public config。
- 配置来源按字段合并：
  - `UI`：该字段来自 UI Store。
  - `Environment`：该字段未设置 UI 值时读取环境变量。
  - `Default`：该字段未设置 UI 和环境变量时使用程序默认。
  - 不得因 UI 设置了某一个字段，就覆盖同 Provider 其他字段的环境变量值。
- `masked_key` 规则：
  - 默认只显示最后四位，例如 `****abcd`。
  - 短 Key 不显示任何片段，只返回 `configured=true`。
  - `masked_key` 只用于展示，不能作为保存输入。

## 7. 新增和修改文件

- 新增计划文件：`plan/plan_stage13_v1.3.3.md`。
- 后端新增：
  - `backend/app/settings/provider_settings.py`
  - `backend/app/settings/secret_store.py`
  - `backend/app/settings/security.py`
  - `backend/app/settings/ssrf_guard.py`
  - `backend/app/schemas/provider_settings.py`
  - `tests/test_provider_settings_*.py`
- 后端修改：
  - `backend/app/main.py`：新增 settings API。
  - `backend/app/services/analysis_service.py`：新增独立开关/授权校验和矛盾请求 `422`。
  - `backend/app/schemas/state.py`：新增任务级统一 `ai_usage`。
  - `backend/app/agents/nodes/teaching_diagram_plan_node.py`：接入 `teaching_narrative_llm_enabled`。
  - `backend/app/agents/nodes/teaching_diagram_review_vlm_node.py`：接入独立 review consent。
  - `backend/app/teaching_diagrams/manifest.py`：避免重复保存普通文本 LLM 统计。
  - `scripts/smoke_image.py`：新增 `--review`。
- 前端新增：
  - `frontend/src/theme/tokens.ts` 或 CSS tokens。
  - `frontend/src/components/ProviderSettingsDrawer.tsx`
  - `frontend/src/components/ProviderSettingsForm.tsx`
  - `frontend/src/components/DashboardOverview.tsx`
  - `frontend/src/components/AIBudgetPanel.tsx`
- 前端修改：
  - `App.tsx`、`AppShell.tsx`、`TaskForm.tsx`、`SummaryCards.tsx`、`ResultTabs.tsx`、`styles.css`、`api/client.ts`、`types/analysis.ts`。
- 不修改：
  - AST、论文解析、Mermaid、全局函数知识库核心实现。
  - 不接入视频或 Seedance。

## 8. 测试计划

- 后端 pytest：
  - 独立授权：论文 VLM consent 不能授权教学图 Review；教学图 Review consent 不能授权论文 VLM。
  - 旧客户端未传 `external_teaching_review_consent` 时 Review 默认 disabled。
  - 图片生成关闭且 Review 开启时返回 `422`，Vision Provider 不被调用。
  - 教学文案 LLM：独立开关、独立预算、cache hit、失败 fallback。
  - 任务级 `ai_usage` 五类统计准确，`teaching_diagram_manifest` 不重复普通文本 LLM 统计。
  - Provider settings：GET/PUT/DELETE/validate/test，Key 不返回，字段级 source 优先级正确。
  - UI 只设置 model 时，环境变量 API Key 和 Base URL 仍生效。
  - `expected_revision` 冲突返回 `409`，不得部分保存。
  - Secret Store：keyring mock、fallback 文件权限、schema_version、revision、原子写入、并发锁、删除 Key、损坏文件、权限错误、写失败不报成功、环境变量只读 fallback。
  - `masked_key` 只显示最后四位，短 Key 不显示片段，masked key 回传被拒。
  - Base URL 和 Provider test SSRF：禁止 localhost、私网 IP、云元数据地址、非 HTTPS、危险重定向、过大响应和超时。
  - `validate` 完全本地零网络；`test` 单次真实请求、无 fallback、需 `confirm_cost=true`。
  - 本机写保护：默认不信任 `X-Forwarded-For`；非本机无 admin token 被拒；Origin 校验失败被拒；Header token 常量时间比较；速率限制生效。
  - SeedreamProvider MockTransport 请求/响应/错误路径。
  - `smoke_image --review` 使用 MockProvider 路径覆盖 pass 与 fallback。
  - 资源释放：pytest 退出无悬挂线程、SQLite lock、未关闭 HTTP client。
- 前端 Vitest：
  - 科技蓝 dashboard 关键区域渲染。
  - 文字对比度、键盘焦点、状态非纯颜色表达、`prefers-reduced-motion` 覆盖关键样式。
  - 小屏侧栏折叠。
  - 设置抽屉打开/关闭、分组切换、保存、删除 Key、validate/test 状态。
  - 设置中心展示字段级来源、revision 冲突提示、configured 和 masked_key。
  - API Key 保存后 input 清空，不写 localStorage/sessionStorage/IndexedDB。
  - 前端关闭 image generation 时自动关闭并禁用 Review。
  - 后端返回 `422` 时前端显示矛盾开关错误。
  - 预算区域分别展示普通 LLM、教学文案、论文 VLM、图片生成、教学图 Review。
- 构建验收：
  - `python -m pytest -q`
  - `npm --prefix frontend test -- --run`
  - `npm --prefix frontend run build`

## 9. 验收标准

- `plan/plan_stage13_v1.3.3.md` 已生成并记录本计划。
- v1.3.3-a 完成后：
  - 教学图 Review 有独立外发授权 `external_teaching_review_consent`。
  - 论文 Figure VLM 的 `external_vision_consent` 与教学图 Review 授权不得互相继承。
  - 图片生成关闭但 Review 开启时，后端返回 `422`，不静默改写请求。
  - 图片生成关闭时，前端自动关闭并禁用 Review。
  - 教学文案 LLM 可独立启用。
  - 任务级 `ai_usage` 可分别展示普通 LLM、教学文案、论文 VLM、图片生成、教学图 Review 的预算、请求数、cache hit。
  - 同步生图约束明确，异步配置不误导用户。
  - `smoke_image.py --review` 覆盖完整闭环。
- v1.3.3-b 完成后：
  - 前端接近参考图的深色科技蓝质感，并满足对比度、键盘焦点、非颜色状态表达和 reduced motion 要求。
  - Provider 设置中心可安全配置六个 Provider。
  - Provider 配置按字段合并，返回非敏感字段来源。
  - 后端不返回真实 API Key，前端不持久化 Key。
  - Secret Store 支持 schema_version、revision、原子写入、并发锁和失败回退。
  - 写接口本机保护、管理员令牌保护、Origin 校验、速率限制生效。
  - Provider Base URL 和 test 接口具备 SSRF 防护。
  - `validate` 保证零费用；`test` 保证最多一次真实 Provider 请求且不自动 fallback。
- 全量后端、前端测试和构建通过。
- 不接入视频或 Seedance，不重构稳定分析主流程。

## 10. 风险与回退方案

- Secret Store 跨平台差异：若 keyring 不可用，自动 fallback 到仓库外权限文件；测试覆盖两条路径。
- Secret Store 写入失败或权限异常：返回明确错误，不标记保存成功；保留环境变量 fallback。
- Provider test 可能产生费用：必须显式 `confirm_cost=true`，前端二次确认，默认不自动测试。
- 自定义 Base URL 带来 SSRF 风险：默认只允许官方地址，自定义 endpoint 和本地模型 endpoint 均需显式高级授权，并统一走 SSRF Guard。
- 科技蓝改版影响现有可用性：保留原组件数据流，只替换布局和 tokens；如风险过高，先落地 dashboard shell，再逐页迁移。
- 授权拆分导致旧客户端不兼容：旧字段保留兼容，但新增教学 Review 必须使用 `external_teaching_review_consent`；旧客户端默认 Review disabled。
- `image_generation_enabled=false` 与 `teaching_review_vlm_enabled=true` 的旧请求会失败：前端自动联动减少误触，后端 `422` 明确提示修正方式。
- 异步生图配置误用：v1.3.3 明确拒绝 async Provider path，并在 public config 中返回 `async_supported=false`。
- 资源释放问题难复现：使用 mock HTTP、临时 SQLite、pytest 超时/线程枚举做回归，避免依赖真实 Provider。
