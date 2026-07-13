#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Backend tests =="
python -m pytest -q

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
