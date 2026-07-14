# v1.2 开发计划：VLM 论文图理解

## 1. 阶段目标

在 v1.1.4 确定性规则分析与文本 LLM 增强保持稳定的前提下，增加本地论文 Figure 提取、筛选和可选 VLM 理解。规则事实始终优先，VLM 输出独立保存并允许失败回退。

版本拆分：v1.2.0 完成本地提取和 Vision 基础设施；v1.2.1 接入两个 Figure 节点；v1.2.2 完成贡献/代码建议关联、前端、报告和验收。

## 2. 本阶段不做什么

不接入 Qwen-Image、Seedream、教学图生成、图片重绘或视频；不默认 OCR；不发送整个 PDF；不修改 AST、Mermaid 和全局函数库工具；自动测试不访问真实 VLM。

## 3. 当前论文流程分析

当前 PaperAnalysis 只处理文本、章节、贡献和规则代码对齐，缺少 Figure 资产、caption、bbox、引用次数和视觉语义。v1.2 通过新增节点增量扩展，不重写稳定流程。

## 4. 总体架构

```text
PDF → 本地 Figure 提取与筛选 → 独立视觉授权 → Qwen-VL/GLM-4.5V
→ JSON/Pydantic/evidence 校验 → FigureAnalysis
→ PaperCodeAlignLLMNode 基于规则和代码 evidence 生成建议关联
```

文本和视觉能力分别使用 `text_llm_enabled`、`vision_vlm_enabled`、`external_text_consent` 和 `external_vision_consent`，支持纯规则、规则+文本、规则+视觉和规则+两者。

## 5. PDF 图片提取

PyMuPDF 逐页提取文本块、image object 和有限 drawing paths；以 caption 为锚点构建 Figure bbox。无法获得独立图片时直接渲染指定 Figure 区域，始终记录页码和 bbox。

## 6. 图注提取

支持 Figure/Fig. 常见大小写和编号形式、有限跨块合并、下方优先兼容上方图注。扫描 PDF 无文本时记录 warning，不默认 OCR。

## 7. 图片去重

MVP 使用 canonical preview SHA-256、原始资产 digest 及同页 caption/bbox 重叠做基础去重。dHash/pHash、复杂多 panel 合并留待真实论文验证后增强。

## 8. 重要 Figure 筛选

根据 architecture/framework/overview/pipeline 等 caption 关键词、正文引用次数、method 类章节、区域大小和可用 preview 稳定排序；应用 Figure 数量上限，未选择项写入 skipped_figures。

## 9. Figure 类型

受控枚举包括 architecture、pipeline、workflow、data_flow、module_detail、training_framework、inference_framework、comparison、result_plot、ablation、qualitative_result、dataset_example 和 other。

## 10. FigureAnalysis Schema

结构包含 figure_id、figure_type、summary、modules、flows、inputs、outputs、visual_relations、contribution_candidates、uncertainties、evidence_refs 和 metadata。`extra=forbid`，禁止 possible_code_links。

## 11. VisionProvider 基类

Provider 统一接收 canonical preview、MIME、结构化上下文、response model 和 token 限制。业务节点只能调用 VisionModelRouter。

## 12. ProviderCapabilities

首版 `supports_json_schema/json_object/tool_calling` 均为 false，统一使用纯 JSON Prompt、本地解析和 Pydantic 校验。只有真实 smoke 成功后才能显式开启增强能力。

## 13. QwenVLProvider

默认 Provider，独立维护 Qwen 图片消息、参数和错误映射；默认不发送 response_format，不记录图片、完整 Prompt 或原始响应。

## 14. GLMVProvider

备用 Provider，拥有独立请求映射，不复用或假定 Qwen/OpenAI 参数兼容；fallback 使用相同 canonical preview 和结构化输入。

## 15. MockVisionProvider

支持成功、非法 JSON、Schema/身份/evidence 错误、timeout、限流、fallback、预算耗尽和 Prompt Injection 场景，自动测试零网络。

## 16. VisionModelRouter

流程为开关/consent检查、缓存、Provider 可用性、原子预算预留、Qwen-VL、校验、受限 retry、GLM fallback。全部失败只写 warning。

## 17. 图片限制

限制单图/总图片字节数、宽高、Figure 数、PDF 页数、image object、原始资产、渲染像素、drawing paths 和提取超时。超限保留已完成结果。

## 18. 预算与并发

视觉逻辑实体和真实 Provider 请求独立于文本预算。每个 retry/fallback 请求发送前原子预留，缓存命中不计请求，达到硬上限后停止外发。

## 19. VLM 缓存

缓存键包含 provider、model、prompt_version、image_hash、caption_hash、task type、Schema version 和结构化上下文 hash。只缓存完整校验成功结果。

## 20. 图片隐私与授权

`external_vision_consent` 由后端独立验证，文本授权绝不能授权图片。只发送筛选后的 canonical preview 和最小上下文，不发送 PDF、未选页面、API key 或完整日志。

## 21. 多模态 Prompt Injection

图片文字、caption 和论文文本全部视为不可信数据。Prompt 明确禁止执行其中指令、改变任务、访问工具、恢复脱敏内容、输出代码目标或 catalog 外贡献。

## 22. PaperFigureExtractNode

位于 paper_analyze 后，本地构建 page_text_index、section_page_map、figure_reference_count、caption candidates、原始资产、canonical previews、selected/skipped figures 和 warnings。

## 23. PaperFigureAnalyzeVLMNode

只输出 Figure 类型、模块、流程、输入输出、视觉关系、contribution 候选和 uncertainties。不得生成代码实体或 possible_code_links。

## 24. Figure 与论文贡献

本地先用章节、caption、正文引用和关键词构建候选；VLM 只能从提供的 contribution catalog 选择，结果明确标记为候选且不覆盖规则事实。

## 25. Figure 与代码实体建议

possible_code_links 由 PaperCodeAlignLLMNode 基于规则论文代码对齐、已校验 FigureAnalysis 和代码 evidence catalog 生成。只能引用 catalog 已有目标，必须标记 `suggested=true`。

## 26. LangGraph 顺序

```text
unzip → repo_scan → code_parse → file_analyze → library_call_extract
→ function_analyze → model_analyze → paper_analyze → paper_figure_extract
→ paper_code_align → file_explain_llm → function_explain_llm → model_explain_llm
→ paper_figure_analyze_vlm → paper_code_align_llm → diagram_generate
→ library_function_doc → report_generate
```

## 27. 输出文件

新增 `paper_figure_analysis.json`、`paper_figures/original/` 和 `paper_figures/previews/`。保存稳定 figure_id、页宽高、rotation、bbox、normalized_bbox、caption、资产、选择状态、VLM 分析、预算和 warnings。

## 28. 前端

TaskForm 独立展示文本和视觉开关/授权/预算。论文页增加 canonical Figure gallery、原始资产信息、VLM 分析、贡献候选和建议性 code links；原规则内容保持优先。

## 29. 报告

末尾增加论文 Figure 理解章节，展示 caption、页码、preview 路径、类型、摘要、贡献候选、不确定性、Provider/缓存/usage，不显示 base64、完整 Prompt 或原始响应。

## 30. Mock 测试

覆盖四种开关组合、独立 consent、稳定 ID/bbox、canonical preview、PDF 安全限制、基础去重、Schema/evidence/身份校验、fallback、预算、缓存、Prompt Injection 和失败隔离。

## 31. smoke_vlm.py

脚本只手动发送无敏感合成 Figure，一次验证一个 Provider，要求费用确认，只输出脱敏 provider/model/latency/usage 和校验摘要；可手动 probe JSON Object，不进入 CI。

## 32. 执行顺序

v1.2.0：配置、Schema、提取工具、Provider/Router/Mock、预算缓存隐私；v1.2.1：两个节点和 Graph；v1.2.2：建议关联、API、前端、报告、文档和最终回归。

## 33. 验收标准

四种能力组合独立运行；两种 consent 后端独立校验；VLM 不读取 PDF、不生成代码目标；canonical preview 为默认图片；安全上限有效；失败不影响规则结果；自动测试零网络。

## 34. 风险与解决方案

复杂 PDF 通过 caption-level 区域渲染和部分结果 warning 降级；供应商兼容差异由独立 Provider 和保守 capability 隔离；成本通过筛选、缓存、预算和并发限制控制；幻觉通过 Schema 和 evidence catalog 限制。

## 35. 文件范围

新增 `backend/app/vision/**`、Figure Schema/Tool/Nodes/Prompt、Figure 前端组件、Vision 测试和 `scripts/smoke_vlm.py`；修改配置、API、State、Graph、PaperCodeAlignLLMNode、报告、前端类型/表单/论文页、README 和相关 docs。不修改稳定 AST、Mermaid、全局函数库和历史计划。
