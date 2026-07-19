#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${CRA_VALIDATE_CONDA_ENV:-}" && "${CRA_VALIDATE_IN_CONDA:-}" != "1" ]]; then
  command -v conda >/dev/null 2>&1 || {
    echo "CRA_VALIDATE_CONDA_ENV requires conda" >&2
    exit 2
  }
  CRA_VALIDATE_IN_CONDA=1 exec conda run -n "$CRA_VALIDATE_CONDA_ENV" bash "$0"
fi

PYTHON_BIN="${PYTHON:-python}"

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info[:2] != (3, 11):
    raise SystemExit(f"Python 3.11 is required; got {sys.version.split()[0]}")
PY

echo "== Backend tests =="
"$PYTHON_BIN" -m pytest -q

echo "== Frontend dependencies =="
npm --prefix frontend ci

echo "== Frontend tests =="
npm --prefix frontend test

echo "== Frontend typecheck =="
npm --prefix frontend run typecheck

echo "== Frontend build =="
npm --prefix frontend run build

cat <<'MSG'

Validation completed.

Optional cleanup before committing:
  bash scripts/clean.sh
MSG
