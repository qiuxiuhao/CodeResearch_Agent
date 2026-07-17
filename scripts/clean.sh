#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Cleaning Python caches..."
find . \( -path './.git' -o -path './data' -o -path './outputs' \) -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +
find . \( -path './.git' -o -path './data' -o -path './outputs' \) -prune -o -name '*.pyc' -type f -exec rm -f {} +
rm -rf .pytest_cache
find . \( -path './.git' -o -path './data' -o -path './outputs' \) -prune -o -name '*.egg-info' -type d -prune -exec rm -rf {} +

echo "Cleaning frontend build artifacts and dependencies..."
rm -rf frontend/node_modules frontend/dist frontend/.vite
find frontend -name '*.tsbuildinfo' -type f -delete

echo "Clean completed. Runtime databases, task outputs, reports, diagrams, and Provider Secrets were preserved."
