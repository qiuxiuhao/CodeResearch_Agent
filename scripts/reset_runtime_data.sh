#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIRM_FLAG="--confirm-delete-runtime-data"
if [[ "$#" -ne 1 || "$1" != "$CONFIRM_FLAG" ]]; then
  cat >&2 <<'MSG'
Runtime data was NOT deleted.

WARNING: this command permanently deletes local SQLite runtime databases,
the global function knowledge base, task outputs, reports, and teaching diagrams.
Provider Secret files are not deleted.

To continue, explicitly run:
  bash scripts/reset_runtime_data.sh --confirm-delete-runtime-data
MSG
  exit 2
fi

cat <<'MSG'
WARNING: permanent runtime data deletion was explicitly confirmed.
The following paths will be deleted if they exist:
MSG

find data -maxdepth 1 \( -name '*.sqlite3' -o -name '*.sqlite3-*' \) -type f -print 2>/dev/null || true
find outputs -mindepth 1 -maxdepth 1 -type d -name 'task_*' -print 2>/dev/null || true

echo "Deleting the listed runtime data..."
find data -maxdepth 1 \( -name '*.sqlite3' -o -name '*.sqlite3-*' \) -type f -delete 2>/dev/null || true
find outputs -mindepth 1 -maxdepth 1 -type d -name 'task_*' -exec rm -rf {} + 2>/dev/null || true

echo "Runtime data reset completed. Provider Secret files were preserved."
