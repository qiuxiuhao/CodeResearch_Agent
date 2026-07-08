# CodeResearch Agent

CodeResearch Agent is a staged project for analyzing deep learning code repositories. v0.1 implements the minimum LangGraph + custom tools loop: unzip a local project ZIP, scan files, parse Python code with `ast`, and write structured outputs.

## v0.1 Features

- Analyze a local ZIP file path.
- Safely extract files into `outputs/{task_id}/source`.
- Scan repository structure and classify common Python project files.
- Parse Python imports, aliases, classes, functions, methods, and line ranges.
- Run the workflow through LangGraph nodes.
- Generate:
  - `repo_index.json`
  - `parsed_files.json`
  - `report.md`

v0.1 intentionally does not include paper parsing, frontend UI, global library knowledge base, diagram generation, RAG, PDF export, or model architecture analysis.

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
  report.md
```

## v0.1 Acceptance

- A small PyTorch-style project ZIP can be analyzed.
- Directory tree and Python files are listed.
- Each Python file's imports, classes, and functions are extracted.
- JSON and Markdown outputs are written.
- Tools and the LangGraph workflow are covered by tests.

