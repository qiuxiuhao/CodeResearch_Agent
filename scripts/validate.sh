#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${CODE_RESEARCH_AGENT_VALIDATE_IN_CONDA:-}" != "1" && "${CONDA_DEFAULT_ENV:-}" != "code-research-agent" ]] && command -v conda >/dev/null 2>&1; then
  CODE_RESEARCH_AGENT_VALIDATE_IN_CONDA=1 exec conda run -n code-research-agent bash "$0"
fi

PYTHON_BIN="${PYTHON:-python}"

echo "== Backend tests =="
"$PYTHON_BIN" -m pytest -q

echo "== Frontend dependencies =="
npm --prefix frontend ci

echo "== Frontend tests =="
npm --prefix frontend test

echo "== Frontend build =="
npm --prefix frontend run build

cat <<'MSG'

Validation completed.

Optional cleanup before committing:
  bash scripts/clean.sh
MSG
