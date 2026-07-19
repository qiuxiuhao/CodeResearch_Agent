#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${CRA_DATA_ROOT:-/root/autodl-tmp/cra}"
BIN_ROOT="$DATA_ROOT/services/bin"
mkdir -p "$BIN_ROOT"

install_verified() {
  local name="$1" url="$2" expected="$3" target="$4" temporary
  [[ -n "$url" && -n "$expected" ]] || {
    echo "$name URL and SHA-256 must be explicitly frozen" >&2
    return 2
  }
  temporary="$(mktemp "$DATA_ROOT/tmp/${name}.XXXXXX")"
  curl --fail --location --proto '=https' --tlsv1.2 "$url" -o "$temporary"
  echo "$expected  $temporary" | sha256sum --check --status || {
    echo "$name checksum mismatch" >&2
    return 3
  }
  install -m 0755 "$temporary" "$target"
  rm -f "$temporary"
}

command -v postgres >/dev/null || {
  echo "Install PostgreSQL 17 from the AutoDL base image package manager before continuing." >&2
  exit 4
}
command -v redis-server >/dev/null || {
  echo "Install Redis 8 from the AutoDL base image package manager before continuing." >&2
  exit 4
}

if [[ ! -x "$BIN_ROOT/minio" ]]; then
  install_verified minio "${MINIO_BINARY_URL:-}" "${MINIO_BINARY_SHA256:-}" "$BIN_ROOT/minio"
fi
if [[ ! -x "$BIN_ROOT/qdrant" ]]; then
  install_verified qdrant "${QDRANT_BINARY_URL:-}" "${QDRANT_BINARY_SHA256:-}" "$BIN_ROOT/qdrant"
fi

echo "Native service binaries verified. Run the database initialization runbook before start.sh."
