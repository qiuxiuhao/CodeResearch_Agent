# API 参考

开发服务器默认地址：

```text
http://127.0.0.1:8000
```

## 健康检查

```text
GET /health
```

返回：

```json
{"status": "ok"}
```

## 分析任务

### 通过本地路径创建任务

```text
POST /analysis/tasks
```

请求体：

```json
{
  "zip_path": "examples/small_pytorch_project.zip",
  "output_root": "outputs",
  "library_db_path": null,
  "paper_pdf_path": null,
  "text_llm_enabled": false,
  "vision_vlm_enabled": false,
  "external_text_consent": false,
  "external_vision_consent": false,
  "teaching_diagrams_enabled": true,
  "image_generation_enabled": false,
  "external_image_consent": false,
  "teaching_review_vlm_enabled": false
}
```

### 上传 ZIP 和可选 PDF

```text
POST /analysis/tasks/upload
```

Multipart 字段：

- `zip_file`：必填，`.zip` 文件
- `paper_pdf`：可选，`.pdf` 文件
- `output_root`：可选，默认 `outputs`
- `library_db_path`：可选
- `text_llm_enabled`：可选，默认 false
- `vision_vlm_enabled`：可选，默认 false
- `external_text_consent`：文本能力启用时必须为 true
- `external_vision_consent`：视觉能力启用时必须为 true
- `teaching_diagrams_enabled`：可选，默认 true，本地 Blueprint 不需要外发授权
- `image_generation_enabled`：可选，默认 false
- `external_image_consent`：AI 教学图视觉层启用时必须为 true
- `teaching_review_vlm_enabled`：可选，默认 false，启用时需要 `external_vision_consent`
- `analysis_mode` / `external_model_consent`：仅用于兼容旧文本能力客户端

任一外部能力未获得对应授权时返回 HTTP 400，且不会创建分析任务或发送外部请求。

## LLM 公共配置

```text
GET /llm/public-config
```

返回非敏感的默认模式、各类逻辑实体上限、总实体上限、真实 Provider 请求上限、最大并发和 Provider 配置状态，不返回 API key。

### 列出任务

```text
GET /analysis/tasks
```

返回最近的 `outputs/task_*` 目录。

### 读取完整任务结果

```text
GET /analysis/tasks/{task_id}
```

返回 summary、各类 JSON 产物、报告文本和缺失文件错误。

### 读取报告

```text
GET /analysis/tasks/{task_id}/report
```

只返回 `report.md`。

### AI 开关与授权

`POST /analysis/tasks` 和 upload form 支持：

- `text_llm_enabled`：是否启用文本 LLM。
- `vision_vlm_enabled`：是否启用论文 VLM。
- `image_generation_enabled`：是否启用 AI 教学图视觉层。
- `teaching_review_vlm_enabled`：是否启用教学图 VLM 审查。
- `external_text_consent`：文本外发授权。
- `external_vision_consent`：论文 Figure 外发授权。
- `external_image_consent`：脱敏 TeachingDiagramSpec 外发给图片生成服务商的授权。

三类授权由后端独立校验。旧 `analysis_mode`/`external_model_consent` 暂时兼容文本能力，但绝不能授权图片生成或视觉审查外发。

`analysis_mode`、`external_model_consent` 和同步创建路由已在 OpenAPI 标记 deprecated，前端只发送独立能力开关与授权字段。Provider 请求中的 `supports_async` 也只保留到 v1.4：未传或 false 被接受并忽略，true 返回 422；该值不会持久化或进入运行时。

## Provider 设置

```text
GET /settings/providers
PUT /settings/providers/{provider_id}
POST /settings/providers/{provider_id}/validate
```

GET 响应只包含脱敏 Key 状态和非敏感字段。如果 Secret Store JSON 可读但某个 UI 字段的类型、有限数值、范围或 domain 列表非法，该字段会被忽略并按 Environment、Default 顺序回退。响应和日志 warning 只记录 Provider/字段名和回退事实，不包含无效原值或 Secret。PUT/validate 的新请求仍会对非法类型和范围返回 422 或显式 validation error，不会将其写入 Secret Store。

### Figure Preview

```text
GET /analysis/tasks/{task_id}/figures/{figure_id}/preview
```

只返回当前任务 `paper_figure_analysis.json` 中登记且位于任务目录内的 canonical preview。

```text
GET /analysis/tasks/{task_id}/figures/{figure_id}/assets/{asset_id}
```

只返回该 Figure 登记的原始 xref/inline 资产，使用相同的任务目录边界校验。

### 公共 AI 配置

```text
GET /llm/public-config
GET /vision/public-config
GET /image-generation/public-config
```

仅返回安全的默认开关、预算、并发、模型名和 Provider 是否配置，不返回 API key。

### 教学图资产

```text
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/blueprint.svg
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/blueprint.png
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/final.png
GET /analysis/tasks/{task_id}/teaching-diagrams/{diagram_id}/raw.png
```

只返回 `teaching_diagrams/manifest.json` 中登记且位于任务目录内的资产。`raw.png` 可能不存在；前端应优先展示通过审查的 `final.png`，否则展示 Blueprint。

## 全局函数库

### 统计信息

```text
GET /library/stats
```

返回函数数量，以及按 package / category / confidence 分组的统计。

全局函数库 API 只围绕库函数解释本身提供查询能力，不提供项目/文件/行号级位置追踪接口。

### 列表、搜索和筛选

```text
GET /library/functions
```

查询参数：

- `query`
- `package_name`
- `category`
- `confidence`
- `limit`
- `offset`
- `sort`：`canonical_name` 或 `updated_at`
- `library_db_path`

### 函数详情

```text
GET /library/functions/{canonical_name}
```

返回完整的教学级函数说明。

### 低置信度函数

```text
GET /library/functions/low-confidence
```

返回低置信度的函数说明。

## Curl 示例

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/analysis/tasks \
  -H "Content-Type: application/json" \
  -d '{"zip_path":"examples/small_pytorch_project.zip"}'
curl http://127.0.0.1:8000/library/stats
curl "http://127.0.0.1:8000/library/functions?query=torch&sort=updated_at"
```
