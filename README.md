# CodeResearch Agent

CodeResearch Agent is a local-first research assistant for understanding unfamiliar deep-learning repositories and connecting code evidence with paper evidence.

## Project Screenshots

The project expects the following images to be uploaded later. They are intentionally placeholders, not generated or claimed screenshots.

```text
docs/assets/project-overview.png
docs/assets/research-agent.png
docs/assets/paper-code-alignment.png
docs/assets/evaluation-dashboard.png
docs/assets/system-architecture.png
```

## Core Capabilities

- Repository ingestion with safe ZIP validation, deterministic source scanning, Python AST parsing, and structured entity extraction.
- Code understanding across files, functions, classes, library calls, model structure, reports, and teaching diagrams.
- Hybrid retrieval over structured code and paper facts with dense, sparse, graph expansion, reranking, and citation validation components.
- Research Agent workflow with planning, tool execution, checkpointing, cancellation, resume, and evidence-grounded answers.
- Paper-code alignment pipeline with candidate generation, scoring, calibration, verification, review state, and stable IDs.
- Evaluation, regression, trace, and bad-case infrastructure for repeatable local validation.
- v2 Local Control Plane with authenticated sessions, workspace/project scope, artifact hashes, and durable job/attempt state.

## System Architecture

```text
Repository ZIP + optional Paper PDF
        |
        v
IndexBuildGraph
  Safe archive -> repo scan -> AST -> symbols -> graph -> structured index
  Paper parse -> sections / figures / formulas -> paper entities
        |
        v
ResearchAgentGraph
  user question -> planner -> tools -> hybrid retrieval -> evidence -> cited answer
        |
        v
Alignment + Evaluation
  paper/code candidates -> scored decisions -> review
  fixture runs -> metrics -> comparisons -> bad cases -> replay
        |
        v
Local v2 Control Plane
  /api/v2 auth -> workspace/project -> artifacts -> jobs -> results -> traces
```

## Technical Highlights

- Rules first, model second: deterministic parsers produce facts; LLM/VLM calls are optional explanation or verification layers.
- Evidence discipline: important outputs are tied to paths, line numbers, entity IDs, paper pages, figure IDs, or retrieval document IDs.
- Local safety boundary: `/api/v2` is the only public business API; legacy handlers are retained only for internal service tests and are hidden from OpenAPI.
- Durable local execution: SQLite-backed jobs, attempts, outbox records, restart recovery, bounded shutdown, cancellation, and heartbeat checks.
- Artifact integrity: uploads are staged, quarantined, validated, finalized by content hash, and rechecked at execution/read boundaries.
- Frontend uses authenticated v2 requests with refresh-token rotation and scoped asset downloads.

## Verifiable Results

Recently verified in this workspace:

```bash
python -m pip check
# No broken requirements found.

cra config validate --config config/local-cpu.yaml
# passed

cra doctor --config config/local-cpu.yaml
# passed with a warning when data/models has not been populated yet

python -m pytest -q
# 489 passed

npm --prefix frontend test
# 20 files, 34 tests passed

npm --prefix frontend run typecheck
npm --prefix frontend run build
# passed; Vite reports large Mermaid-related chunks as a warning

CRA_VALIDATE_CONDA_ENV=cra-v2-local bash scripts/validate.sh
# passed
```

Full-suite validation should be run before tagging a release:

```bash
python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
bash scripts/validate.sh
```

## Quick Start

```bash
conda create -n cra-v2-local python=3.11 pip -y
conda activate cra-v2-local
python -m pip install --upgrade pip
python -m pip install -e ".[dev,secrets,retrieval,agent,observability]"
python -m pip check

cra config validate --config config/local-cpu.yaml
cra doctor --config config/local-cpu.yaml

npm --prefix frontend ci
npm --prefix frontend run build

CRA_SERVE_FRONTEND=true \
CRA_FRONTEND_DIST="$PWD/frontend/dist" \
cra serve --config config/local-cpu.yaml
```

Open the app at:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/api/v2/health
```

For frontend development:

```bash
bash scripts/dev.sh
```

## Project Boundaries

- This repository presents the Local v2 single-node profile: FastAPI, React, SQLite, local artifacts, and an in-process job backend.
- Docker, Compose, Team deployment, Redis, Celery, PostgreSQL, S3/MinIO, and multi-user production operations are outside the maintained resume scope.
- The system does not load a local LLM. External text, vision, and image providers require explicit configuration and user consent.
- No fake screenshots, benchmark numbers, or provider smoke-test results are claimed here.
- Legacy API modules may remain importable for internal tests, but they are not the public HTTP contract.
