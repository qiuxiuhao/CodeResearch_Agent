from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path

from .config import DeploymentProfile, PlatformSettings, sqlite_path
from .jobs import CeleryJobBackend, InProcessJobBackend, JobBackend
from .store import LocalControlPlaneStore
from .store import ControlPlaneError


@dataclass(slots=True)
class ControlPlaneRuntime:
    settings: PlatformSettings
    store: object
    jobs: JobBackend
    identity: object | None = None
    artifacts: object | None = None
    analysis_executor: object | None = None
    _local_lock_fd: int | None = None

    @classmethod
    def build(cls, settings: PlatformSettings | None = None) -> "ControlPlaneRuntime":
        settings = settings or PlatformSettings.from_env()
        if settings.profile is DeploymentProfile.LOCAL:
            descriptor = _claim_local_runtime_lock(settings)
            try:
                store = LocalControlPlaneStore(sqlite_path(settings.control_database_url))
                store.migrate()
                identity = _build_local_identity(store, settings)
                from .artifacts import LocalArtifactStore
                from .domain_handlers import (
                    build_alignment_handler, build_analysis_handler,
                    build_delete_handler, build_evaluation_handler, build_export_handler,
                    build_index_handler, build_maintenance_handler, build_replay_handler,
                    build_research_handler, LocalAnalysisExecutor,
                )

                artifacts = LocalArtifactStore(settings.artifact_root)
                jobs = InProcessJobBackend(store)
                output_root = settings.artifact_root / "derived"
                analysis_executor = LocalAnalysisExecutor(max_workers=1)
                jobs.register(
                    "analysis", build_analysis_handler(
                        store, artifacts, output_root, analysis_executor,
                    ),
                )
                jobs.register(
                    "indexing", build_index_handler(
                        store, artifacts, output_root, analysis_executor,
                    ),
                )
                jobs.register("research", build_research_handler())
                jobs.register("alignment", build_alignment_handler())
                jobs.register("evaluation", build_evaluation_handler())
                jobs.register("replay", build_replay_handler(store, artifacts))
                jobs.register("export", build_export_handler(store, artifacts))
                # Backup/restore remain internal verification helpers until a real offline
                # restore contract exists. The v2 API fails closed before creating a Job.
                jobs.register("maintenance", build_maintenance_handler(store, artifacts))
                jobs.register("delete", build_delete_handler(store, artifacts))
                return cls(
                    settings=settings, store=store, jobs=jobs, identity=identity,
                    artifacts=artifacts, analysis_executor=analysis_executor,
                    _local_lock_fd=descriptor,
                )
            except Exception:
                _release_local_runtime_lock(descriptor)
                raise
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
        try:
            shutdown = getattr(self.jobs, "shutdown", None)
            if shutdown:
                await shutdown()
        finally:
            executor_shutdown = getattr(self.analysis_executor, "shutdown", None)
            if executor_shutdown:
                executor_shutdown()
            self._release_local_lock()

    async def start(self) -> None:
        self._acquire_local_lock()
        start = getattr(self.jobs, "start", None)
        try:
            if start:
                await start()
        except Exception:
            self._release_local_lock()
            raise

    def acquire_startup_lock(self) -> None:
        self._acquire_local_lock()

    def _acquire_local_lock(self) -> None:
        if self.settings.profile is not DeploymentProfile.LOCAL or self._local_lock_fd is not None:
            return
        self._local_lock_fd = _claim_local_runtime_lock(self.settings)

    def _release_local_lock(self) -> None:
        if self._local_lock_fd is None:
            return
        descriptor, self._local_lock_fd = self._local_lock_fd, None
        _release_local_runtime_lock(descriptor)


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


def _claim_local_runtime_lock(settings: PlatformSettings) -> int:
    lock_path = sqlite_path(settings.control_database_url).with_suffix(".runtime.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise ControlPlaneError("local_runtime_already_running") from exc
    return descriptor


def _release_local_runtime_lock(descriptor: int) -> None:
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
