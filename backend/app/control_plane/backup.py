from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .schemas import BackupManifest


@dataclass(frozen=True, slots=True)
class RestoreInventory:
    database_backup_id: str
    artifact_snapshot_id: str
    artifact_hash_catalog: str
    available_secret_references: frozenset[str]
    database_schema_version: str


class RestoreVerificationError(ValueError):
    pass


def verify_restore_inventory(manifest: BackupManifest, inventory: RestoreInventory) -> None:
    checks = {
        "database_backup_mismatch": inventory.database_backup_id == manifest.database_backup_id,
        "artifact_snapshot_mismatch": inventory.artifact_snapshot_id == manifest.artifact_snapshot_id,
        "artifact_catalog_mismatch": inventory.artifact_hash_catalog == manifest.artifact_hash_catalog,
        "database_schema_mismatch": inventory.database_schema_version == manifest.database_schema_version,
        "secret_backup_missing": manifest.secret_backup_reference in inventory.available_secret_references,
    }
    failures = [code for code, passed in checks.items() if not passed]
    if failures:
        raise RestoreVerificationError(",".join(failures))


def backup_manifest_digest(manifest: BackupManifest) -> str:
    return hashlib.sha256(
        manifest.model_dump_json(exclude_none=False).encode("utf-8")
    ).hexdigest()

