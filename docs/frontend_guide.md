# Frontend Guide

The frontend is a React + Vite + TypeScript workbench.

## Main Tabs

- Overview: high-level task metrics and output status.
- Files: file-level analysis grouped by repository role.
- Functions: function-level purpose, logic, inputs, outputs, and library calls.
- Library Functions: library notes generated for the current task.
- Global Function Library: SQLite-backed searchable function knowledge base.
- Models: `nn.Module` classes, layers, forward steps, and component candidates.
- Paper: optional paper parsing and paper-code alignment results.
- Diagrams: Mermaid diagrams generated from structured analysis artifacts.
- Report: generated Markdown report.

## Normal Mode

Normal mode is designed for users who already know Python and deep learning basics. It keeps more structured data visible and prioritizes scanning.

## Beginner Mode

Beginner mode emphasizes library calls inside function details:

- Canonical function name.
- Call text and line number.
- Category and confidence.
- Teaching-level modal with explanation, parameters, return value, examples, shape notes, and common mistakes.

Low-confidence unknown calls are intentionally shown with weaker styling or skipped in places where they could be misleading.

## Mermaid

Mermaid diagrams are rendered in the browser when possible. If rendering fails, the frontend falls back to the Mermaid source code block.

v1.0 does not export diagrams as PNG, SVG, PDF, or Graphviz.
