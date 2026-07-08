# API Reference

The development server runs at:

```text
http://127.0.0.1:8000
```

## Health

```text
GET /health
```

Returns:

```json
{"status": "ok"}
```

## Analysis Tasks

### Create Task From Local Paths

```text
POST /analysis/tasks
```

Body:

```json
{
  "zip_path": "examples/small_pytorch_project.zip",
  "output_root": "outputs",
  "library_db_path": null,
  "paper_pdf_path": null
}
```

### Upload ZIP And Optional PDF

```text
POST /analysis/tasks/upload
```

Multipart fields:

- `zip_file`: required `.zip`
- `paper_pdf`: optional `.pdf`
- `output_root`: optional, default `outputs`
- `library_db_path`: optional

### List Tasks

```text
GET /analysis/tasks
```

Returns recent `outputs/task_*` directories.

### Read Full Task Result

```text
GET /analysis/tasks/{task_id}
```

Returns summary, JSON artifacts, report text, and missing-file errors.

### Read Report

```text
GET /analysis/tasks/{task_id}/report
```

Returns only `report.md`.

## Global Library

### Stats

```text
GET /library/stats
```

Returns function count, occurrence count, and grouped package/category/confidence counts.

### List And Search Functions

```text
GET /library/functions
```

Query parameters:

- `query`
- `package_name`
- `category`
- `confidence`
- `limit`
- `offset`
- `sort`: `canonical_name`, `updated_at`, or `occurrence_count`
- `library_db_path`

### Function Detail

```text
GET /library/functions/{canonical_name}
```

Returns a full teaching-level function note with aggregate occurrence stats.

### Function Occurrences

```text
GET /library/functions/{canonical_name}/occurrences
```

Returns task/file/function line history for a global library function.

### High Frequency Functions

```text
GET /library/functions/high-frequency
```

Returns functions sorted by occurrence count.

### Low Confidence Functions

```text
GET /library/functions/low-confidence
```

Returns low-confidence function notes.

## Curl Examples

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/analysis/tasks \
  -H "Content-Type: application/json" \
  -d '{"zip_path":"examples/small_pytorch_project.zip"}'
curl http://127.0.0.1:8000/library/stats
curl "http://127.0.0.1:8000/library/functions?query=torch&sort=occurrence_count"
```
