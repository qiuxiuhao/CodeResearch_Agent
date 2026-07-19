#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="${CRA_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DATA_ROOT="${CRA_DATA_ROOT:-/root/autodl-tmp/cra}"
ENV_PREFIX="${CRA_ENV_PREFIX:-$DATA_ROOT/envs/cra-v2}"
CRA_REPO_ROOT="$REPO_ROOT" CRA_DATA_ROOT="$DATA_ROOT" \
  "$ENV_PREFIX/bin/supervisorctl" -c "$REPO_ROOT/deploy/autodl/supervisord.conf" shutdown
