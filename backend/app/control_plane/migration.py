from __future__ import annotations

from dataclasses import dataclass

from .schemas import LocalToTeamMigration


STAGES = [
    "created", "scanning", "validating", "ready", "importing",
    "rebuilding_indexes", "verifying", "cutover_ready", "completed",
]


@dataclass(frozen=True, slots=True)
class MigrationItem:
    object_type: str
    object_id: str
    content_hash: str


def detect_id_collisions(source: list[MigrationItem], target: list[MigrationItem]) -> list[str]:
    target_by_identity = {(item.object_type, item.object_id): item.content_hash for item in target}
    return [
        item.object_id for item in source
        if (existing := target_by_identity.get((item.object_type, item.object_id))) is not None
        and existing != item.content_hash
    ]


def advance_migration(migration: LocalToTeamMigration, target_status: str) -> LocalToTeamMigration:
    if migration.status in {"failed", "rolling_back", "rolled_back", "completed"}:
        raise ValueError("migration_terminal")
    current = STAGES.index(migration.status)
    if current + 1 >= len(STAGES) or STAGES[current + 1] != target_status:
        raise ValueError("invalid_migration_transition")
    completed = list(migration.completed_stages)
    completed.append(migration.status)
    return migration.model_copy(update={"status": target_status, "completed_stages": completed})
