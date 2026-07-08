#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Cleaning Python caches..."
find . -name __pycache__ -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -type f -delete
rm -rf .pytest_cache code_research_agent.egg-info

echo "Cleaning frontend build artifacts and dependencies..."
rm -rf frontend/node_modules frontend/dist frontend/.vite
find frontend -maxdepth 1 -name '*.tsbuildinfo' -type f -delete

echo "Cleaning local runtime data..."
find data -maxdepth 1 \( -name '*.sqlite3' -o -name '*.sqlite3-*' \) -type f -delete
find outputs -mindepth 1 -maxdepth 1 -type d -name 'task_*' -exec rm -rf {} +

echo "Clean completed."
