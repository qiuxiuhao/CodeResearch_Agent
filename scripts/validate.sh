#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Backend tests =="
conda run -n code-research-agent pytest -q

echo "== Frontend dependencies =="
npm --prefix frontend ci

echo "== Frontend tests =="
npm --prefix frontend test

echo "== Frontend build =="
npm --prefix frontend run build

cat <<'MSG'

Validation completed.

Optional cleanup before committing:
  find . -name __pycache__ -type d -prune -exec rm -rf {} +
  find . -name '*.pyc' -type f -delete
  rm -rf .pytest_cache code_research_agent.egg-info frontend/node_modules frontend/dist frontend/.vite frontend/*.tsbuildinfo data/*.sqlite3 data/*.sqlite3-* outputs/task_*
MSG
