# FAQ

## Why not just send the whole repository to an LLM?

The project aims to produce stable, traceable artifacts. AST parsing and deterministic rules create evidence before any possible future model enhancement.

## Does the tool execute user code?

No. The analysis pipeline reads files and parses source text. It does not import or execute code from the uploaded repository.

## Why SQLite for the global function library?

SQLite is local, simple, portable, and enough for a personal learning knowledge base. It also keeps the project easy to run for demos.

## Why Mermaid instead of Graphviz?

Mermaid source can be embedded directly in Markdown and rendered by many tools. v1.0 prioritizes readable report diagrams over heavy rendering infrastructure.

## Why is analysis synchronous?

Synchronous tasks are simpler for an MVP and easier to explain. A queue-based worker system can be added later if analysis becomes slow.

## Does v1.0 support login?

No. v1.0 is a local-first developer tool and demo project.

## Does v1.0 export PDF reports?

No. Reports are generated as Markdown. PDF export is intentionally out of scope.

## Does paper parsing understand formulas and figures?

No. Paper parsing is an MVP based on text extraction and heuristic matching.
