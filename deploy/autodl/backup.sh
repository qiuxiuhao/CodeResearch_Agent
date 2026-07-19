#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${CRA_DATA_ROOT:-/root/autodl-tmp/cra}"
BACKUP_ROOT="${CRA_BACKUP_ROOT:-$DATA_ROOT/backups}"
PG_SERVICE="${CRA_PG_SERVICE:?CRA_PG_SERVICE must name a protected libpq service}"
MC_ALIAS="${CRA_MC_ALIAS:?CRA_MC_ALIAS must name a configured MinIO alias}"
SECRET_BACKUP_REFERENCE="${CRA_SECRET_BACKUP_REFERENCE:?encrypted Secret backup reference required}"
APP_VERSION="${CRA_APPLICATION_VERSION:-2.0.0-dev}"
API_VERSION="${CRA_API_CONTRACT_VERSION:-2}"
DB_SCHEMA_VERSION="${CRA_DATABASE_SCHEMA_VERSION:-unknown}"

for command in pg_dump mc sha256sum python; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 2; }
done

umask 077
window="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$BACKUP_ROOT/$window"
temporary="$BACKUP_ROOT/.${window}.staging"
[[ ! -e "$destination" && ! -e "$temporary" ]] || {
  echo "backup window already exists: $window" >&2
  exit 3
}
mkdir -p "$temporary/database" "$temporary/artifacts"

# libpq credentials come from a 0600 PGSERVICEFILE/PGPASSFILE, never this script or argv.
pg_dump service="$PG_SERVICE" --format=custom --file="$temporary/database/control.dump"
pg_dump service="$PG_SERVICE" --schema-only --file="$temporary/database/schema.sql"

# Versioning is not a backup. Mirror into an independently configured backup alias/bucket.
mc mirror --overwrite --preserve "$MC_ALIAS/cra-artifacts" "$temporary/artifacts/"

(cd "$temporary" && find artifacts -type f -exec sha256sum {} + \
  | sort > artifact-hashes.sha256)
(cd "$temporary" && sha256sum database/control.dump database/schema.sql \
  > database-hashes.sha256)

BACKUP_DESTINATION="$temporary" \
BACKUP_WINDOW="$window" \
BACKUP_APP_VERSION="$APP_VERSION" \
BACKUP_API_VERSION="$API_VERSION" \
BACKUP_SCHEMA_VERSION="$DB_SCHEMA_VERSION" \
BACKUP_SECRET_REFERENCE="$SECRET_BACKUP_REFERENCE" \
python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["BACKUP_DESTINATION"])
manifest = {
    "schema_version": "2.0",
    "backup_manifest_id": f"backup_{os.environ['BACKUP_WINDOW']}",
    "application_version": os.environ["BACKUP_APP_VERSION"],
    "api_contract_version": os.environ["BACKUP_API_VERSION"],
    "database_schema_version": os.environ["BACKUP_SCHEMA_VERSION"],
    "database_backup_id": "database/control.dump",
    "wal_position": None,
    "artifact_snapshot_id": "artifacts",
    "artifact_hash_catalog": "artifact-hashes.sha256",
    "secret_backup_reference": os.environ["BACKUP_SECRET_REFERENCE"],
    "qdrant_rebuild_manifest": "rebuild from Control/Domain DB and Artifact catalog",
    "created_at": os.environ["BACKUP_WINDOW"],
    "complete": False,
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
)
PY

sync
mv "$temporary" "$destination"
echo "$destination"
echo "Logical DB and Artifact snapshot created. WAL/PITR and encrypted Secret backup are external gates."
