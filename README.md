# CodeResearch Agent

CodeResearch Agent is a staged project for analyzing deep learning code repositories. v0.8.1 keeps the deterministic backend pipeline from earlier stages and adds a browser-based MVP for creating tasks, viewing analysis results, switching between normal and beginner modes, and opening teaching explanations for Python / PyTorch / NumPy library calls.

## v0.8.1 Features

- Analyze a local ZIP file path through CLI or API.
- Upload a ZIP and optional paper PDF through the browser API.
- Safely extract files into `outputs/{task_id}/source`.
- Scan repository structure and classify common Python project files.
- Parse Python imports, aliases, classes, functions, methods, and line ranges.
- Generate deterministic file-level and function-level analysis.
- Identify Python / PyTorch / NumPy / OpenCV / PIL / einops library calls.
- Store and reuse teaching-level Python library function explanations in SQLite.
- Detect PyTorch-style `nn.Module` model classes, layers, forward flow, and component candidates.
- Optionally parse a local paper PDF with PyMuPDF and align paper contributions to code with confidence labels.
- Generate Mermaid source diagrams for project structure, model flow, core modules, function logic, and paper-code alignment.
- Provide a React + Vite frontend MVP with:
  - project overview
  - file-level analysis
  - function-level analysis
  - Python library function notes
  - model network analysis
  - paper parsing and paper-code alignment
  - diagram analysis
  - report view
- Support normal mode / beginner mode switching in the frontend.
- In beginner mode, show function-level `library_calls` prominently.
- Click a library function call to open a teaching explanation modal.

v0.8.1 intentionally does not include a global library management page, PDF export, Graphviz rendering, PNG/SVG diagram export, complex login, complex RAG, or paper figure/table parsing.

## Environment

Use one shared Conda environment for the backend:

```bash
conda create -n code-research-agent python=3.11 -y
conda activate code-research-agent
pip install -e ".[dev]"
```

For the frontend:

```bash
cd frontend
npm ci
```

Do not commit `frontend/node_modules/`; frontend dependencies should be restored from `frontend/package-lock.json` with `npm ci`.

## Run Backend

Run the example ZIP from the CLI:

```bash
python -m backend.app.services.analysis_service examples/small_pytorch_project.zip
```

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

Start the FastAPI development server:

```bash
uvicorn backend.app.main:app --reload
```

## Run Frontend

In another terminal:

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

The frontend uses a Vite proxy for `/api/*` requests to `http://127.0.0.1:8000`.

Mermaid may produce a build-size warning during `npm run build`. This does not block the v0.8.1 frontend MVP; a later stage can reduce bundle size with dynamic imports or code splitting.

## API

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

List recent tasks:

```bash
curl http://127.0.0.1:8000/analysis/tasks
```

Read a complete task result:

```bash
curl http://127.0.0.1:8000/analysis/tasks/task_example123
```

Read only the Markdown report:

```bash
curl http://127.0.0.1:8000/analysis/tasks/task_example123/report
```

Upload a ZIP and optional PDF:

```bash
curl -X POST http://127.0.0.1:8000/analysis/tasks/upload \
  -F "zip_file=@examples/small_pytorch_project.zip" \
  -F "paper_pdf=@examples/paper.pdf"
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
  diagrams.json
  library_function_docs.json
  report.md
```

## Test

Backend:

```bash
pytest -q
```

Frontend:

```bash
cd frontend && npm test
cd frontend && npm run build
```

## v0.8.1 Acceptance

- A small PyTorch-style project ZIP can be analyzed from CLI, JSON API, or upload API.
- Existing backend outputs continue to be written.
- `GET /analysis/tasks` lists recent task output directories.
- `GET /analysis/tasks/{task_id}` returns structured JSON outputs and `report.md`.
- The frontend can create a task and load the result.
- The frontend displays overview, files, functions, library docs, models, paper analysis, diagrams, and report tabs.
- Normal mode / beginner mode can be switched without rerunning analysis.
- Beginner mode shows function-level `library_calls`.
- Clicking a library call opens a teaching explanation modal when documentation exists, with fallback text when it does not.
- Mermaid diagrams render in the browser or fall back to Mermaid code.
- Backend pytest passes.
- Frontend tests and build pass.
