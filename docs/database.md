# 数据库说明

CodeResearch Agent 使用 SQLite 存储全局 Python 函数教学知识库。

这个知识库只记录库函数本身的教学级解释，例如一句话作用、通俗解释、常见参数、返回值、代码例子、shape 注意事项和常见误区。它不记录库函数在每个项目、文件、函数或行号中的出现位置。

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
