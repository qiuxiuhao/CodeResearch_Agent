# Architecture

CodeResearch Agent is a local-first code understanding system for deep learning repositories and optional paper PDFs. The v1.0 architecture keeps the analysis pipeline deterministic and exposes results through JSON files, Markdown reports, and a React frontend.

## Layers

- FastAPI API layer: task creation, upload, result reading, report reading, and global library query APIs.
- LangGraph workflow layer: orchestrates repository extraction, parsing, analysis, documentation, diagram generation, and report generation.
- Tool layer: deterministic static-analysis utilities for repository scanning, AST parsing, model detection, paper parsing, paper-code alignment, Mermaid generation, and report building.
- Service layer: `analysis_service` coordinates a single analysis run; `library_function_service` manages the SQLite-backed global Python function library.
- Schema layer: Pydantic models define stable JSON structures for repository, file, function, model, paper, diagram, and library outputs.
- Frontend layer: React + Vite workbench for task creation, result browsing, beginner-mode explanations, diagrams, and global library exploration.

## Data Flow

1. User provides a ZIP file path or uploads a ZIP through the browser.
2. Optional paper PDF path or upload is attached.
3. The backend creates a task and extracts the ZIP into `outputs/{task_id}/source`.
4. LangGraph nodes produce structured JSON artifacts.
5. The report node writes `report.md`.
6. The API reads task artifacts from `outputs/{task_id}`.
7. The frontend renders the result across overview, file, function, library, model, paper, diagram, and report tabs.
8. Library function explanations are persisted in SQLite and can be browsed globally.

## Runtime Artifacts

The project intentionally keeps generated data out of Git:

- `outputs/task_*`
- `data/*.sqlite3`
- `frontend/node_modules`
- `frontend/dist`
- Python caches and egg-info metadata

See [Validation](validation.md) for cleanup commands.
