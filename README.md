# CodeResearch Agent

CodeResearch Agent is a staged project for analyzing deep learning code repositories. v0.3.1 builds on the LangGraph + custom tools loop: unzip a local project ZIP, scan files, parse Python code with `ast`, add file-level analysis, add function-level analysis, identify basic library calls, and write structured outputs.

## v0.3.1 Features

- Analyze a local ZIP file path.
- Safely extract files into `outputs/{task_id}/source`.
- Scan repository structure and classify common Python project files.
- Parse Python imports, aliases, classes, functions, methods, and line ranges.
- Generate deterministic file-level analysis for every Python file.
- Classify Python files as entry, model, training, inference, dataset, config-related, utility, package init, ordinary module, or unknown.
- Generate deterministic function-level analysis for every Python function and method.
- Identify basic Python / PyTorch / NumPy / OpenCV / PIL / einops library calls from function bodies.
- Run the workflow through LangGraph nodes.
- Generate:
  - `repo_index.json`
  - `parsed_files.json`
  - `file_analysis.json`
  - `library_calls.json`
  - `function_analysis.json`
  - `report.md`

v0.3.1 intentionally does not include global library knowledge base persistence, library function documentation, paper parsing, frontend UI, diagram generation, RAG, PDF export, or model architecture analysis.

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
  -d '{"zip_path":"examples/small_pytorch_project.zip"}'
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
  report.md
```

## v0.3.1 Acceptance

- A small PyTorch-style project ZIP can be analyzed.
- Directory tree and Python files are listed.
- Each Python file's imports, classes, and functions are extracted.
- Each Python file has one file-level analysis entry.
- Each Python function and method has one function-level analysis entry.
- Basic library calls are written to `library_calls.json`.
- `report.md` includes a `逐文件分析` section.
- `report.md` includes a `逐函数分析` section.
- JSON and Markdown outputs are written.
- Tools and the LangGraph workflow are covered by tests.
