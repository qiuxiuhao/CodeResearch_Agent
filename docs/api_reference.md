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
  "paper_pdf_path": null
  ,"analysis_mode": "rule"
  ,"external_model_consent": false
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
- `analysis_mode`：`rule` 或 `hybrid`，缺省按环境变量后回退 `rule`
- `external_model_consent`：hybrid 必须为 `true`

hybrid 未授权时返回 HTTP 400，且不会创建分析任务或发送外部请求。

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
