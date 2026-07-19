#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_ROOT="${CRA_DATA_ROOT:-/root/autodl-tmp/cra}"
ENV_PREFIX="${CRA_ENV_PREFIX:-$DATA_ROOT/envs/cra-v2}"
CONFIG_PATH="${CRA_CONFIG_PATH:-$REPO_ROOT/config/team-autodl-gpu.yaml}"

mkdir -p "$DATA_ROOT"/{artifacts,backups,logs,models,run,secrets,services,tmp}
chmod 700 "$DATA_ROOT/secrets"

command -v conda >/dev/null || { echo "conda is required" >&2; exit 2; }
command -v nvidia-smi >/dev/null || { echo "NVIDIA runtime is required" >&2; exit 2; }
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

cpu_count="$(getconf _NPROCESSORS_ONLN)"
memory_gib="$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)"
disk_gib="$(df -Pk "$DATA_ROOT" | awk 'NR==2 {printf "%d", $4/1024/1024}')"
if (( cpu_count < 8 || memory_gib < 32 || disk_gib < 100 )); then
  echo "Team profile requires >=8 CPU cores, >=32 GiB RAM and >=100 GiB free disk" >&2
  exit 3
fi

if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  conda create -y -p "$ENV_PREFIX" python=3.11 pip
fi
"$ENV_PREFIX/bin/python" -m pip install --require-hashes -r "$REPO_ROOT/requirements-gpu-cu12.txt"
"$ENV_PREFIX/bin/python" -m pip install --require-hashes -r "$REPO_ROOT/requirements-team.txt"
"$ENV_PREFIX/bin/python" -m pip install --no-deps -e "$REPO_ROOT"
"$ENV_PREFIX/bin/python" -m pip check

npm --prefix "$REPO_ROOT/frontend" ci
npm --prefix "$REPO_ROOT/frontend" run build
"$ENV_PREFIX/bin/cra" config validate --config "$CONFIG_PATH" >/dev/null
"$ENV_PREFIX/bin/cra" models prefetch --config "$CONFIG_PATH"
"$ENV_PREFIX/bin/cra" models verify --config "$CONFIG_PATH"

echo "Bootstrap complete. Install native services, configure protected secrets, then run start.sh."
