# Agent Workflow

The analysis workflow is implemented as a LangGraph pipeline. Nodes exchange a shared state object and write deterministic artifacts into the task output directory.

## Node Order

```text
unzip
repo_scan
code_parse
file_analyze
library_call_extract
function_analyze
model_analyze
paper_analyze
paper_code_align
diagram_generate
library_function_doc
report_generate
```

## Node Responsibilities

- `unzip`: safely extracts the input ZIP into a task-local source directory.
- `repo_scan`: indexes Python files and classifies likely entry, model, training, inference, and config files.
- `code_parse`: uses Python AST parsing to extract imports, aliases, classes, functions, methods, and line ranges.
- `file_analyze`: produces deterministic file-level purpose and project-position summaries.
- `library_call_extract`: identifies Python / PyTorch / NumPy / PIL / OpenCV / einops style library calls.
- `function_analyze`: summarizes function purpose, inputs, outputs, implementation logic, and library calls.
- `model_analyze`: detects `nn.Module` style model classes, layers, forward flow, and component candidates.
- `paper_analyze`: optionally parses a local paper PDF and extracts title, abstract, contributions, keywords, and module names.
- `paper_code_align`: aligns paper contributions to files, classes, functions, and model modules with confidence labels.
- `diagram_generate`: creates Mermaid source diagrams from existing structured artifacts.
- `library_function_doc`: writes and reuses teaching-level library function notes in SQLite.
- `report_generate`: saves all final JSON artifacts and builds `report.md`.

## Design Principles

- Deterministic static analysis first.
- No execution of user project code.
- No network retrieval inside the analysis pipeline.
- Evidence and confidence fields are preferred over unsupported claims.
- Missing optional inputs, such as paper PDFs, should produce empty structures rather than breaking code analysis.
