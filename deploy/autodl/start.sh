#!/usr/bin/env bash
set -euo pipefail
export CRA_REPO_ROOT="${CRA_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export CRA_DATA_ROOT="${CRA_DATA_ROOT:-/root/autodl-tmp/cra}"
export CRA_ENV_PREFIX="${CRA_ENV_PREFIX:-$CRA_DATA_ROOT/envs/cra-v2}"
exec "$CRA_ENV_PREFIX/bin/supervisord" -c "$CRA_REPO_ROOT/deploy/autodl/supervisord.conf"
