# v1.3 开发计划：教学图生成

## 1. 阶段目标

在保留现有 Mermaid 工程结构图的基础上，新增面向初学者的教学图生成能力。同一任务最终提供：

- Mermaid 工程结构图：继续来自现有 `diagrams.json`。
- 本地确定性准确教学图：由规则事实生成 Blueprint，保证无任何 API Key 时也可生成。
- AI 视觉教学图：AI 只提供视觉层或参考风格，最终图由本地程序确定性合成。

核心流程：

```text
规则事实 + diagrams.json
→ TeachingDiagramSkeletonBuilder
→ TeachingDiagramSkeleton
→ DeepSeek/Qwen 生成 TeachingDiagramNarrative
→ TeachingDiagramSpecAssembler
→ TeachingDiagramSpec
→ BlueprintRenderer
→ Qwen-Image/Seedream 生成 generated_raw.png
→ TeachingDiagramCompositor 生成 styled_composite.png/final.png
→ Qwen-VL/GLM Review styled_composite
→ 合格展示 final.png；不合格回退 Blueprint
```

## 2. 本阶段不做什么

不实现动态教学视频；不接入 Seedance；不修改稳定 AST、论文解析、Mermaid 和全局函数知识库实现；不把完整源码、完整仓库或完整论文交给图像模型；不让 AI 图片覆盖 Blueprint；不把供应商原始图片直接作为最终图；自动测试不真实调用外部模型。

## 3. 当前流程分析

当前 v1.2.4 Mermaid 由 `diagram_generate` 基于规则产物生成 `diagrams.json`。文本 LLM 默认 DeepSeek、备用 Qwen，已有脱敏、预算、缓存、evidence 校验。论文 VLM 默认 Qwen-VL、备用 GLM-4.5V，只读筛选后的 Figure preview。v1.3 复用这些边界，但教学文案、图片生成、图片审查分别使用独立开关、授权和预算。

## 4. v1.3 总体架构

新增：

```text
TeachingDiagramSkeleton
TeachingDiagramSkeletonBuilder
TeachingDiagramNarrative
TeachingDiagramSpecAssembler
TeachingDiagramSpec
BlueprintRenderer
TeachingDiagramCompositor
SafeImageDownloader
TeachingDiagramReviewCache
```

规则事实是唯一结构来源。模块、连接、连接方向、输入输出、Tensor Shape 和公式必须由规则分析、`model_analysis`、`function_analysis` 或 `diagrams.json` 确定性生成。DeepSeek/Qwen 只能生成通俗解释、分区标题、教学步骤、一句话总结、学习提示、布局和配色建议，不得新增、删除或改写模块、连接、Shape 和公式。

## 5. 教学图适用实体选择规则

默认最多 4 张，允许 0 到 4 张。低于质量阈值的实体不生成，不强制凑满。优先级：

- 主模型类和 `forward_steps`。
- 核心函数，优先 `forward`、`train`、`predict`。
- 数据输入输出链路。
- Mermaid 中已有 `model_flow`、`core_modules`、`function_logic` 对应实体。
- 论文贡献到代码的已校验对齐。

## 6. TeachingDiagramSkeleton

`TeachingDiagramSkeleton` 由本地确定性生成，字段包括：

- `skeleton_id`
- `source_entity`
- `related_mermaid_diagram_ids`
- `sections`
- `modules`
- `inputs`
- `outputs`
- `connections`
- `shapes`
- `formulas`
- `legend_items`
- `evidence_refs`
- `warnings`
- `skeleton_hash`

校验：所有模块、连接、Shape、公式必须引用合法 evidence。合法 evidence 不能被用于伪造错误连接，例如不能用两个节点各自存在的 evidence 构造规则中不存在的边。

## 7. TeachingDiagramSkeletonBuilder

输入：

```text
repo_index, file_analysis, function_analysis, library_calls,
model_analysis, paper_analysis, paper_code_alignment,
diagrams, llm_explanations, paper_figure_analysis
```

明确不输入 `library_function_docs`，因为 `TeachingDiagramPlanNode` 执行时 `LibraryFunctionDocNode` 尚未执行，不调整稳定主流程。

职责：

- 从规则产物和 `diagrams.json` 选择实体。
- 建立 `diagram_evidence_catalog`。
- 生成 skeleton、连接方向、输入输出、Shape、公式和 Mermaid 映射。
- 生成稳定 `diagram_id`：基于 source entity、skeleton hash、schema version，由本地程序生成，不由 LLM 生成。

## 8. TeachingDiagramNarrative

DeepSeek/Qwen 只生成 Narrative：

- `section_titles`
- `plain_language_explanations`
- `teaching_steps`
- `one_sentence_summary`
- `learning_tips`
- `layout_suggestions`
- `color_suggestions`

Narrative 必须绑定 skeleton id 和 skeleton hash。Assembler 校验 LLM 未改变 skeleton 模块、连接、Shape、公式；任何结构性差异都丢弃 Narrative，并回退本地模板文案。

## 9. TeachingDiagramSpecAssembler

`TeachingDiagramSpecAssembler` 将 Skeleton 和 Narrative 合成 `TeachingDiagramSpec`。结构字段只来自 Skeleton，教学文案只来自 Narrative 或本地模板。

`public_spec_hash` 由本地程序生成：先移除 hash 字段，对脱敏 public spec 做 canonical JSON 序列化，再 SHA-256。不得由 LLM 生成。

## 10. TeachingDiagramSpec Schema

`TeachingDiagramSpec` 增加：

- `schema_version`
- `diagram_id`
- `related_mermaid_diagram_ids`
- `source_entity`
- `skeleton_hash`
- `public_spec_hash`
- `sections`
- `modules`
- `inputs`
- `outputs`
- `connections`
- `shapes`
- `formulas`
- `legend`
- `steps`
- `one_sentence_summary`
- `learning_tips`
- `style_hints`
- `evidence_refs`
- `warnings`

`extra="forbid"`。禁止 Markdown fence、HTML script、任意 SVG 片段、未脱敏 secret。

## 11. Mermaid 映射

`TeachingDiagramPlanNode` 必须读取 `diagrams.json`，并为每个教学图写入 `related_mermaid_diagram_ids`。前端三图切换必须依据该字段建立明确映射：

- Mermaid：展示相关 Mermaid 图。
- Blueprint：展示同一 Spec 的本地确定性图。
- AI：展示同一 Spec 的 final 图。

若找不到相关 Mermaid 图，仍可生成 Blueprint，但 manifest 写 warning。

## 12. BlueprintRenderer

`BlueprintRenderer` 必须本地确定性生成 SVG 和 PNG，并满足：

- 中文字体 fallback。
- 字体缺失 warning。
- XML/SVG escape。
- 文本换行。
- 长文本裁剪。
- 受控公式文本。
- 不执行外部 LaTeX。
- 不接受模型生成的任意 SVG。
- SVG 和 PNG 使用同一确定性布局。
- 禁止 script、foreignObject、外链资源。

## 13. 确定性最终合成层

新增 `TeachingDiagramCompositor`。供应商图片不得直接成为最终图。

输出：

```text
generated_raw.png
styled_composite.png
final.png
```

规则：

- `generated_raw.png` 是供应商视觉层或风格参考。
- `styled_composite.png` 由本地程序叠加准确模块文字、Tensor Shape、公式、箭头、图例。
- `final.png` 是通过审查后的最终展示图。
- VLM Review 检查 `styled_composite.png`，不是仅检查 raw image。
- raw 图失败或不合格时，Blueprint 仍可展示。

## 14. 外部调用开关、授权和预算

三类外部调用分别处理：

- DeepSeek/Qwen 教学文案规划：需要 `text_llm_enabled=true` 和 `external_text_consent=true`。
- Qwen-Image/Seedream 图片生成：需要 `image_generation_enabled=true` 和 `external_image_consent=true`。
- Qwen-VL/GLM 图片审查：需要 `teaching_review_vlm_enabled=true` 和 `external_vision_consent=true`。

新增独立预算：

```text
TEACHING_PLAN_MAX_LLM_REQUESTS
TEACHING_IMAGE_MAX_PROVIDER_REQUESTS
TEACHING_REVIEW_MAX_PROVIDER_REQUESTS
```

文本授权不能授权图片生成；图片授权不能授权 VLM 审查；视觉授权不能授权图片生成。

## 15. Image Provider 与 Router

新增独立 `backend/app/image_generation/**`：

- `ImageProviderCapabilities`
- `QwenImageProvider`
- `SeedreamProvider`
- `MockImageProvider`
- `ImageGenerationRouter`

模型名和 Base URL 全部通过环境变量配置，不根据品牌假设参数兼容。Qwen-Image 默认，Seedream 备用。每张图最多一次 fallback。

## 16. SafeImageDownloader 与异步轮询

若供应商返回异步任务或图片 URL，必须使用 `SafeImageDownloader`：

- 只允许 HTTPS。
- 供应商域名 allowlist。
- 禁止 localhost、私网 IP、云元数据地址。
- 重定向后重新校验。
- 限制下载字节和超时。
- 禁止 `file`、`ftp` 等协议。

异步轮询限制：

```text
IMAGE_TASK_MAX_POLL_SECONDS
IMAGE_TASK_POLL_INTERVAL_SECONDS
IMAGE_TASK_MAX_POLL_ATTEMPTS
```

超时或超次数后写 warning，回退 Blueprint，不阻断主流程。

## 17. Image Cache

SQLite 只保存 metadata。图片使用内容寻址文件系统：

```text
data/image_generation_cache/<hash-prefix>/<sha256>.png
```

缓存异常非阻断：

- get 失败继续 Provider。
- set 失败保留有效结果。
- warning 记录 `image_cache_error`。
- 不泄露完整异常和绝对路径。

缓存键至少包含：

```text
provider, model, prompt_version, schema_version,
public_spec_hash, diagram_spec_hash, width, height
```

## 18. Teaching Diagram Review Cache

新增 Review Cache。缓存键至少包含：

```text
review_provider
review_model
review_prompt_version
review_schema_version
generated_image_hash
public_spec_hash
```

只缓存通过 Schema 校验的 Review 结果。命中缓存不消耗审查请求预算。

## 19. 图片安全校验

生成或下载的图片必须验证：

- MIME 与 magic bytes。
- 文件大小。
- 像素宽高。
- 总像素数。
- 实际图片解码。
- 禁止 SVG、HTML、脚本、外链资源作为 AI 图。
- 必要时规范化转 PNG。

## 20. TeachingDiagramPlanNode

位于 `diagram_generate` 后，输入包含 `diagrams.json` 对应 State `diagrams`，不包含 `library_function_docs`。输出 skeleton、narrative、spec、evidence catalog、warnings 和预算快照。无外部文本授权时使用本地 Narrative 模板，保证零外部请求可生成 Blueprint。

## 21. TeachingDiagramGenerateNode

职责：

- 先生成 Blueprint SVG/PNG。
- 可选调用 Image Router 生成 `generated_raw.png`。
- 调用 Compositor 生成 `styled_composite.png`。
- 未启用图片生成或无授权时跳过 AI，保留 Blueprint。
- 单图失败不影响其他图。

## 22. TeachingDiagramReviewVLMNode

默认 Qwen-VL，备用 GLM-4.5V。审查对象是 `styled_composite.png`。Review 通过后复制或登记为 `final.png`；不通过则 `display_variant=blueprint`。

通过条件包括：

- 无 hallucinated modules。
- 无错误连接。
- 无错误 Shape。
- 无错误公式。
- 关键文字、箭头、图例可读。
- 安全分满分。

## 23. Manifest 原子写入

`manifest.json` 由主线程聚合后写入。并发工作线程不得直接同时写 manifest。保存必须使用临时文件和原子 rename，避免半写入文件。

目录结构：

```text
outputs/{task_id}/teaching_diagrams/
  manifest.json
  specs/{diagram_id}.json
  blueprint_svg/{diagram_id}.svg
  blueprint_png/{diagram_id}.png
  ai/{diagram_id}/generated_raw.png
  ai/{diagram_id}/styled_composite.png
  ai/{diagram_id}/final.png
```

## 24. LangGraph 接入顺序

```text
... → paper_code_align_llm → diagram_generate
→ teaching_diagram_plan
→ teaching_diagram_generate
→ teaching_diagram_review_vlm
→ library_function_doc
→ report_generate
```

不调整 `library_function_doc` 的稳定位置。

## 25. API 与前端

新增图片读取 API：

```text
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/blueprint.svg
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/blueprint.png
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/final.png
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/raw.png
GET /image-generation/public-config
```

前端 `DiagramsPanel` 增加 Mermaid/Blueprint/AI 三图切换。AI 图显示时必须提示可能简化；AI 不合格时明确展示 Blueprint 回退原因。

## 26. 报告章节

`report.md` 新增“教学图”章节，展示：

- 状态、预算和授权。
- 每张图的 Mermaid 映射。
- Blueprint 路径。
- raw/composite/final 状态。
- Review 分数和 fallback reason。
- AI 图可能简化，规则事实和 Blueprint 优先。

不保存或展示完整 Prompt、API Key、完整供应商响应。

## 27. Mock 测试

新增测试覆盖：

- LLM 不能修改 Skeleton 模块或连接。
- 合法 evidence 不能被用于伪造错误连接。
- `related_mermaid_diagram_ids` 映射。
- local planner 零外部请求。
- AI raw 图不直接成为 final。
- compositor 文字、Shape、公式和箭头保持准确。
- SafeImageDownloader SSRF 防护。
- 异步轮询超时。
- image cache get/set 故障回退。
- unknown provider exception 请求统计。
- manifest 并发原子写入。
- review cache 命中。
- 中文文字、长文本和 SVG 注入测试。
- 自动测试使用 MockImageProvider 和 MockVisionProvider。

## 28. 分版本执行顺序

v1.3.0：

- Schema、Skeleton、SkeletonBuilder、SpecAssembler。
- BlueprintRenderer。
- Image Provider/Router/Mock。
- SafeImageDownloader。
- Image Cache 和 Review Cache。
- 单元测试。

v1.3.1：

- Plan/Generate/Review 三个节点。
- Compositor。
- LangGraph 和 State 接入。
- manifest 原子写入。
- workflow 测试。

v1.3.2：

- API、前端三图切换、报告。
- `smoke_image.py`。
- README、docs、`.env.example`。
- 最终验收。

## 29. 验收标准

- 未配置任何图像 API Key 时可生成 0 到 4 张 Blueprint，不影响 Mermaid。
- 模块、连接、方向、输入输出、Shape、公式全部来自规则事实或 `diagrams.json`。
- DeepSeek/Qwen 不得改变结构。
- AI raw 图不能直接作为 final。
- final 图必须经过本地 Compositor。
- VLM 审查 `styled_composite.png`。
- AI 不合格时回退 Blueprint。
- 三类外部授权独立生效。
- 缓存和 manifest 故障不破坏主流程。
- 自动测试零真实网络。
- 不接入视频。

## 30. 文件范围

新增：

```text
backend/app/schemas/teaching_diagram.py
backend/app/teaching_diagrams/skeleton.py
backend/app/teaching_diagrams/skeleton_builder.py
backend/app/teaching_diagrams/narrative.py
backend/app/teaching_diagrams/spec_assembler.py
backend/app/teaching_diagrams/blueprint_renderer.py
backend/app/teaching_diagrams/compositor.py
backend/app/teaching_diagrams/manifest.py
backend/app/image_generation/**
backend/app/agents/nodes/teaching_diagram_plan_node.py
backend/app/agents/nodes/teaching_diagram_generate_node.py
backend/app/agents/nodes/teaching_diagram_review_vlm_node.py
scripts/smoke_image.py
tests/test_teaching_diagram_*.py
```

修改：

```text
backend/app/schemas/state.py
backend/app/agents/graph.py
backend/app/agents/nodes/report_generate_node.py
backend/app/services/analysis_service.py
backend/app/main.py
frontend/src/types/analysis.ts
frontend/src/api/client.ts
frontend/src/components/TaskForm.tsx
frontend/src/components/DiagramsPanel.tsx
README.md
docs/*.md
.env.example
```

不修改：

```text
backend/app/tools/ast_parse_tool.py
backend/app/tools/paper_parse_tool.py
backend/app/tools/mermaid_tool.py
backend/app/services/library_function_service.py
```
