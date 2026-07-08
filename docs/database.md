# 数据库说明

CodeResearch Agent 使用 SQLite 存储全局 Python 函数知识库。

## 默认路径

```text
data/python_function_library.sqlite3
```

可以通过以下方式覆盖：

- `LIBRARY_DB_PATH`
- `run_analysis(..., library_db_path=...)`
- API 请求字段 `library_db_path`

## 数据表

### `library_functions`

每个标准库函数保存一条教学级说明。

主要字段：

- `canonical_name`
- `display_name`
- `package_name`
- `category`
- `summary`
- `beginner_explanation`
- `parameters_explanation`
- `return_explanation`
- `common_usage`
- `code_example`
- `shape_or_tensor_note`
- `common_mistakes`
- `related_functions`
- `confidence`
- `created_at`
- `updated_at`

## Git 提交规则

本地 SQLite 文件属于运行时数据，不应提交：

```text
data/*.sqlite3
data/*.sqlite3-*
data/*.db
```

数据库 schema 会在服务首次使用时自动创建。
