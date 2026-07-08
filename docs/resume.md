# Resume Notes

## Short Version

CodeResearch Agent: built a FastAPI + LangGraph + React code understanding tool for deep learning repositories, supporting AST-based repository analysis, function/model structure extraction, paper-code alignment, Mermaid diagrams, and a SQLite-backed Python function knowledge library.

## Long Version

- Designed a LangGraph workflow that turns a ZIP repository and optional paper PDF into structured JSON artifacts, Markdown reports, and frontend views.
- Implemented deterministic AST-based parsing for imports, aliases, classes, functions, methods, library calls, and PyTorch-style model structures.
- Built a global SQLite knowledge library for Python / PyTorch / NumPy function explanations, including search, filters, occurrence history, high-frequency functions, and low-confidence function review.
- Added MVP paper parsing and heuristic paper-code alignment with confidence labels and evidence.
- Generated Mermaid diagrams for project structure, model flow, core modules, function logic, and paper-code alignment.
- Built a React + Vite frontend with normal mode and beginner mode, including library function explanation modals.

## Technical Keywords

FastAPI, LangGraph, Python AST, Pydantic, SQLite, PyMuPDF, Mermaid, React, Vite, TypeScript, static analysis, code intelligence, deep learning tooling.

## Interview Hook

The project is useful to explain because it is not just a frontend demo or a prompt wrapper. It has a real pipeline, persistent knowledge base, structured artifacts, test coverage, and clear engineering tradeoffs.
