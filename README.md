# CodeResearch Agent

CodeResearch Agent is a staged project for analyzing deep learning code repositories. v0.6.1 builds on the LangGraph + custom tools loop: unzip a local project ZIP, scan files, parse Python code with `ast`, add file-level analysis, add function-level analysis, identify basic library calls, detect model network structure, optionally parse a paper PDF, align paper contributions to code, persist reusable library function notes in SQLite, and write structured outputs.

## v0.6.1 Features

- Analyze a local ZIP file path.
- Safely extract files into `outputs/{task_id}/source`.
- Scan repository structure and classify common Python project files.
- Parse Python imports, aliases, classes, functions, methods, and line ranges.
- Generate deterministic file-level analysis for every Python file.
- Classify Python files as entry, model, training, inference, dataset, config-related, utility, package init, ordinary module, or unknown.
- Generate deterministic function-level analysis for every Python function and method.
- Identify basic Python / PyTorch / NumPy / OpenCV / PIL / einops library calls from function bodies.
- Detect PyTorch-style `nn.Module` model classes.
- Extract `__init__` layer assignments and basic `forward` data-flow steps.
- Identify model component candidates such as encoder, decoder, backbone, head, classifier, activation, normalization, and loss.
- Optionally parse a local paper PDF with PyMuPDF.
- Extract paper title, abstract, method text, contribution candidates, keywords, and module names.
- Align paper contributions to code files, classes, functions, and model modules with confidence labels.
- Keep paper contribution extraction and paper-code alignment conservative: generic wording alone is not treated as a confirmed match, and unmatched contributions include a reason.
- Store reusable Python library function explanations in SQLite.
- Record library function occurrences for each analysis task.
- Reuse existing global library function explanations across tasks.
- Generate concise teaching notes for current-task library functions.
- Run the workflow through LangGraph nodes.
- Generate:
  - `repo_index.json`
  - `parsed_files.json`
  - `file_analysis.json`
  - `library_calls.json`
  - `function_analysis.json`
  - `model_analysis.json`
  - `paper_analysis.json`
  - `paper_code_alignment.json`
  - `library_function_docs.json`
  - `report.md`

v0.6.1 intentionally does not include a frontend library page, library function popups, complex RAG, complex formula parsing, graph generation enhancement, frontend pages, or PDF report export.

## Environment

Use one shared Conda environment for the whole project:

```bash
conda create -n code-research-agent python=3.11 -y
conda activate code-research-agent
pip install -e ".[dev]"
```

For later stages, keep using the same environment:

```bash
conda activate code-research-agent
```

## Run

Run the example ZIP:

```bash
python -m backend.app.services.analysis_service examples/small_pytorch_project.zip
```

The command prints a JSON summary with the `task_id`, output directory, and report path.

Optionally pass a local paper PDF path:

```bash
python -m backend.app.services.analysis_service examples/small_pytorch_project.zip --paper-pdf-path examples/paper.pdf
```

By default, the global library function database is stored at:

```text
data/python_function_library.sqlite3
```

You can override it with an environment variable or CLI flag:

```bash
LIBRARY_DB_PATH=/tmp/code_research_library.sqlite3 python -m backend.app.services.analysis_service examples/small_pytorch_project.zip
python -m backend.app.services.analysis_service examples/small_pytorch_project.zip --library-db-path /tmp/code_research_library.sqlite3
```

## API

Start the development server:

```bash
uvicorn backend.app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Start an analysis from a local ZIP path:

```bash
curl -X POST http://127.0.0.1:8000/analysis/tasks \
  -H "Content-Type: application/json" \
  -d '{"zip_path":"examples/small_pytorch_project.zip","paper_pdf_path":"examples/paper.pdf"}'
```

## Test

```bash
pytest
```

## Output Layout

Each run writes to:

```text
outputs/{task_id}/
  source/
  repo_index.json
  parsed_files.json
  file_analysis.json
  library_calls.json
  function_analysis.json
  model_analysis.json
  paper_analysis.json
  paper_code_alignment.json
  library_function_docs.json
  report.md
```

## v0.6.1 Acceptance

- A small PyTorch-style project ZIP can be analyzed.
- Directory tree and Python files are listed.
- Each Python file's imports, classes, and functions are extracted.
- Each Python file has one file-level analysis entry.
- Each Python function and method has one function-level analysis entry.
- Basic library calls are written to `library_calls.json`.
- PyTorch-style model classes are written to `model_analysis.json`.
- The example `SimpleNet` model is detected as the main model candidate.
- `__init__` layers and basic `forward` steps are extracted for model classes.
- If no paper PDF is provided, empty paper analysis outputs are still written and code analysis succeeds.
- If a paper PDF is provided, paper title, abstract, method text, contribution candidates, keywords, and module names are written to `paper_analysis.json`.
- Paper-code alignment results with status and confidence are written to `paper_code_alignment.json`.
- Generic paper/code word overlap alone does not force a matched alignment.
- Unmatched paper contributions include `contribution_id`, `contribution_title`, and `reason`.
- Confirmed library calls are written to the global SQLite knowledge base.
- Reused library function explanations are written to `library_function_docs.json`.
- Library function occurrences are recorded per task.
- `report.md` includes a `逐文件分析` section.
- `report.md` includes a `逐函数分析` section.
- `report.md` includes a `模型网络结构分析` section.
- `report.md` includes a `论文解析与论文代码对齐` section.
- `report.md` includes a `Python 库函数说明` section.
- JSON and Markdown outputs are written.
- Tools and the LangGraph workflow are covered by tests.
