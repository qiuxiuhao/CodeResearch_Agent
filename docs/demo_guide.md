# Demo Guide

This guide walks through a complete local demo.

## 1. Start The App

```bash
bash scripts/dev.sh
```

Open:

```text
http://127.0.0.1:5173
```

The backend health check is:

```text
http://127.0.0.1:8000/health
```

## 2. Create A Task

Use path mode and enter:

```text
examples/small_pytorch_project.zip
```

Create the task and wait for analysis to finish.

## 3. Recommended Presentation Order

1. Overview: show file/function/model/diagram counts.
2. Files: show file-level purpose and project position.
3. Functions: select a function and explain function-level analysis.
4. Beginner mode: toggle beginner mode and click a library function chip.
5. Models: show `SimpleNet`, layers, inputs, outputs, and forward flow.
6. Diagrams: show Mermaid project/model/function diagrams.
7. Global Library: show searchable Python function notes and occurrence history.
8. Report: show the Markdown report as a single generated deliverable.

## 4. Optional Paper Demo

If a local paper PDF is available, provide it in the optional paper field. v1.0 performs MVP text extraction and heuristic paper-code alignment. It does not parse figures, tables, or formulas.

## 5. What To Say

This project is intentionally not a black-box prompt wrapper. It builds structured evidence from deterministic AST analysis, then renders it in a human-friendly frontend.
