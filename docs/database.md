# Database

CodeResearch Agent uses SQLite for the global Python function knowledge library.

## Default Path

```text
data/python_function_library.sqlite3
```

This can be overridden with:

- `LIBRARY_DB_PATH`
- `run_analysis(..., library_db_path=...)`
- API request field `library_db_path`

## Tables

### `library_functions`

Stores one teaching-level note per canonical library function.

Key fields:

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

### `library_function_occurrences`

Stores where each library function appeared.

Key fields:

- `canonical_name`
- `task_id`
- `project_name`
- `file_path`
- `function_name`
- `qualified_function_name`
- `class_name`
- `line_no`
- `call_text`
- `created_at`

## Git Policy

Local SQLite files are runtime data and should not be committed:

```text
data/*.sqlite3
data/*.sqlite3-*
data/*.db
```

The schema is created automatically by the service when the database is first used.
