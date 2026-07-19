from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .config import DeploymentProfile, PlatformSettings, sqlite_path
from .jobs import CeleryJobBackend, InProcessJobBackend, JobBackend
from .store import LocalControlPlaneStore


@dataclass(slots=True)
class ControlPlaneRuntime:
    settings: PlatformSettings
    store: object
    jobs: JobBackend
    identity: object | None = None
    artifacts: object | None = None

    @classmethod
    def build(cls, settings: PlatformSettings | None = None) -> "ControlPlaneRuntime":
        settings = settings or PlatformSettings.from_env()
        if settings.profile is DeploymentProfile.LOCAL:
            store = LocalControlPlaneStore(sqlite_path(settings.control_database_url))
            store.migrate()
            identity = _build_local_identity(store, settings)
            from .artifacts import LocalArtifactStore
            from .domain_handlers import (
                build_alignment_handler, build_analysis_handler, build_backup_handler,
                build_delete_handler, build_evaluation_handler, build_export_handler,
                build_index_handler, build_maintenance_handler, build_replay_handler,
                build_research_handler, build_restore_handler,
            )

            artifacts = LocalArtifactStore(settings.artifact_root)
            jobs = InProcessJobBackend(store)
            output_root = settings.artifact_root / "derived"
            jobs.register("analysis", build_analysis_handler(store, artifacts, output_root))
            jobs.register("indexing", build_index_handler(store, artifacts, output_root))
            jobs.register("research", build_research_handler())
            jobs.register("alignment", build_alignment_handler())
            jobs.register("evaluation", build_evaluation_handler())
            jobs.register("replay", build_replay_handler(store, artifacts))
            jobs.register("export", build_export_handler(store, artifacts))
            jobs.register("backup", build_backup_handler(store, artifacts))
            jobs.register("restore", build_restore_handler(store, artifacts))
            jobs.register("maintenance", build_maintenance_handler(artifacts))
            jobs.register("delete", build_delete_handler(store, artifacts))
            return cls(
                settings=settings, store=store, jobs=jobs, identity=identity, artifacts=artifacts,
            )
        from .team_store import PostgresControlPlaneStore

        store = PostgresControlPlaneStore(settings.control_database_url)
        store.check_connectivity()
        from .artifacts import S3ArtifactStore

        artifacts = S3ArtifactStore(
            settings.s3_endpoint_url or "", settings.s3_bucket or "",
            access_key=os.getenv("AWS_ACCESS_KEY_ID"), secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        return cls(
            settings=settings, store=store, jobs=CeleryJobBackend(store), artifacts=artifacts,
        )

    async def shutdown(self) -> None:
        shutdown = getattr(self.jobs, "shutdown", None)
        if shutdown:
            await shutdown()


def _build_local_identity(store: LocalControlPlaneStore, settings: PlatformSettings) -> object | None:
    try:
        from .auth import Argon2PasswordHasher, LocalIdentityService

        hasher = Argon2PasswordHasher()
    except RuntimeError:
        return None
    encoded = os.getenv("CRA_SIGNING_KEY")
    if encoded:
        key = encoded.encode("utf-8")
    else:
        key_path = Path(settings.artifact_root).parent / ".local_signing_key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(os.urandom(48))
            key_path.chmod(0o600)
        key = key_path.read_bytes()
    return LocalIdentityService(
        store, hasher, key, access_minutes=settings.access_token_minutes,
        refresh_days=settings.refresh_token_days,
        bootstrap_token=os.getenv("CRA_BOOTSTRAP_TOKEN"),
    )
