#!/usr/bin/env bash
set -euo pipefail

backup_directory="${1:?usage: restore-verify.sh <isolated-backup-directory>}"
backup_directory="$(cd "$backup_directory" && pwd)"
[[ -f "$backup_directory/manifest.json" ]] || { echo "manifest missing" >&2; exit 2; }
[[ -f "$backup_directory/database/control.dump" ]] || { echo "database dump missing" >&2; exit 2; }
[[ -f "$backup_directory/artifact-hashes.sha256" ]] || {
  echo "artifact hash catalog missing" >&2
  exit 2
}

for command in pg_restore sha256sum python; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 2; }
done

python - "$backup_directory/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
required = {
    "backup_manifest_id", "application_version", "database_schema_version",
    "database_backup_id", "artifact_snapshot_id", "artifact_hash_catalog",
    "secret_backup_reference", "qdrant_rebuild_manifest",
}
missing = sorted(required - manifest.keys())
if missing:
    raise SystemExit("manifest fields missing: " + ",".join(missing))
if not manifest["secret_backup_reference"]:
    raise SystemExit("secret backup reference missing")
PY

(cd "$backup_directory" && sha256sum --check database-hashes.sha256)
if [[ -s "$backup_directory/artifact-hashes.sha256" ]]; then
  (cd "$backup_directory" && sha256sum --check artifact-hashes.sha256)
fi
pg_restore --list "$backup_directory/database/control.dump" >/dev/null

echo "Backup bytes and dump catalog verified. Restore into a new isolated PostgreSQL/MinIO environment next."
echo "This command never overwrites the running production environment."
