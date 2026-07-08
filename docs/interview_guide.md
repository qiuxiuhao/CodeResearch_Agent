# Interview Guide

## 3-Minute Version

1. Problem: deep learning repositories are hard to understand quickly, especially for beginners.
2. Solution: CodeResearch Agent analyzes a ZIP and optional paper PDF, then produces structured JSON, reports, diagrams, and a frontend workbench.
3. Core design: FastAPI API, LangGraph workflow, AST-based tools, SQLite library knowledge base, React frontend.
4. Result: users can inspect files, functions, model structure, paper-code alignment, diagrams, and beginner-friendly library explanations.

## 8-Minute Version

1. Explain the architecture layers.
2. Walk through the LangGraph node order.
3. Show why AST static analysis is safer and more stable than executing user code.
4. Explain model detection and forward-flow extraction as deterministic MVP analysis.
5. Explain the global function library and occurrence history.
6. Explain normal mode versus beginner mode.
7. Discuss confidence labels, warnings, and evidence as anti-hallucination design.

## 15-Minute Version

1. Start with the user workflow from ZIP input to frontend result.
2. Open the docs and show architecture/workflow diagrams conceptually.
3. Walk through key schemas and why structured artifacts matter.
4. Explain paper parsing and alignment limitations.
5. Explain Mermaid diagram generation and traceability.
6. Discuss testing strategy.
7. Close with roadmap: async tasks, better visualization, optional RAG, PDF export, deployment.

## Tradeoffs To Mention

- Static analysis is incomplete but safe and explainable.
- SQLite is simple and ideal for a local-first learning knowledge base.
- Synchronous analysis is acceptable for MVP demos; a production version would use a queue.
- Mermaid source is easier to inspect and version than rendered image artifacts.
