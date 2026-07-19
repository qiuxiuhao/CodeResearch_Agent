#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "Starting CodeResearch Agent backend..."
conda run -n code-research-agent cra serve --config config/local-cpu.yaml --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Starting CodeResearch Agent frontend..."
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!

echo ""
echo "Frontend: http://127.0.0.1:5173"
echo "Backend health: http://127.0.0.1:8000/health"
echo "Press Ctrl+C to stop both processes."
echo ""

wait "$BACKEND_PID" "$FRONTEND_PID"
