#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:?service name required}"
REPO_ROOT="${CRA_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DATA_ROOT="${CRA_DATA_ROOT:-/root/autodl-tmp/cra}"
ENV_PREFIX="${CRA_ENV_PREFIX:-$DATA_ROOT/envs/cra-v2}"
export CRA_CONFIG_PATH="${CRA_CONFIG_PATH:-$REPO_ROOT/config/team-autodl-gpu.yaml}"
export PYTHONUNBUFFERED=1
export CRA_SERVE_FRONTEND=true
export CRA_FRONTEND_DIST="$REPO_ROOT/frontend/dist"
export PATH="$DATA_ROOT/services/bin:$ENV_PREFIX/bin:$PATH"
cd "$REPO_ROOT"

case "$SERVICE" in
  api) exec cra serve --config "$CRA_CONFIG_PATH" --host 127.0.0.1 --port 6006 ;;
  inference) exec cra inference --config "$CRA_CONFIG_PATH" ;;
  dispatcher) exec python -m backend.app.control_plane.team_process dispatcher ;;
  beat) exec python -m backend.app.control_plane.team_process beat ;;
  worker-analysis)
    export CRA_WORKER_QUEUES="cra.analysis,cra.indexing"
    exec celery -A backend.app.control_plane.celery_worker:app worker -Q "$CRA_WORKER_QUEUES" --concurrency=1 --prefetch-multiplier=1
    ;;
  worker-research)
    export CRA_WORKER_QUEUES="cra.research,cra.alignment"
    exec celery -A backend.app.control_plane.celery_worker:app worker -Q "$CRA_WORKER_QUEUES" --concurrency=1 --prefetch-multiplier=1
    ;;
  worker-evaluation)
    export CRA_WORKER_QUEUES="cra.evaluation,cra.replay"
    exec celery -A backend.app.control_plane.celery_worker:app worker -Q "$CRA_WORKER_QUEUES" --concurrency=1 --prefetch-multiplier=1
    ;;
  worker-maintenance)
    export CRA_WORKER_QUEUES="cra.export,cra.backup,cra.restore,cra.maintenance"
    exec celery -A backend.app.control_plane.celery_worker:app worker -Q "$CRA_WORKER_QUEUES" --concurrency=1 --prefetch-multiplier=1
    ;;
  *) echo "unknown service: $SERVICE" >&2; exit 2 ;;
esac
