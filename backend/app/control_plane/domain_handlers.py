from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from backend.app.services.analysis_service import run_analysis
from backend.app.agents.research.schemas import ResearchRunCreateRequest
from backend.app.alignment.schemas import AlignmentRunCreateRequest
from backend.app.evaluation.schemas import EvaluationRunCreateRequest

from .artifacts import (
    ArchiveLimits, ArtifactSecurityError, LocalArtifactStore, extract_validated_archive,
    validate_archive, validate_pdf_header,
)
from .jobs import JobExecutionContext
from .schemas import ArtifactExecutionRef, ArtifactRecord, JobRecord
from .store import ControlPlaneError, LocalControlPlaneStore


class AnalysisJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_artifact: ArtifactExecutionRef | None = None
    paper_artifact: ArtifactExecutionRef | None = None
    repository_storage_key: str | None = Field(default=None, min_length=1, max_length=1000)
    paper_storage_key: str | None = Field(default=None, max_length=1000)
    repository_key: str | None = Field(default=None, max_length=500)
    text_llm_enabled: bool = False
    teaching_narrative_llm_enabled: bool = False
    vision_vlm_enabled: bool = False
    external_text_consent: bool = False
    external_vision_consent: bool = False
    teaching_diagrams_enabled: bool = True
    image_generation_enabled: bool = False
    external_image_consent: bool = False
    teaching_review_vlm_enabled: bool = False
    external_teaching_review_consent: bool = False


class ResearchJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_id: str
    request: ResearchRunCreateRequest


class AlignmentJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_id: str
    request: AlignmentRunCreateRequest


class EvaluationJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: EvaluationRunCreateRequest


class IndexJobPayload(AnalysisJobPayload):
    pass


class ArtifactListPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_ids: list[str] = Field(min_length=1, max_length=200)


class BackupJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="manual", min_length=1, max_length=100)


class RestoreJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backup_artifact_id: str = Field(min_length=1, max_length=128)


class MaintenanceJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(default="cleanup_staging", pattern=r"^cleanup_staging$")
    older_than_seconds: int = Field(default=86_400, ge=3600, le=31_536_000)


class DeleteJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(min_length=1, max_length=128)


class LocalAnalysisExecutor:
    """Dedicated executor so Analysis never occupies asyncio's shared default pool."""

    def __init__(self, *, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="cra-local-analysis",
        )

    async def run(self, function, /, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, partial(function, *args, **kwargs))

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_analysis_handler(
    store: LocalControlPlaneStore, artifacts: LocalArtifactStore, output_root: Path,
    analysis_executor: LocalAnalysisExecutor | None = None,
):
    executor = analysis_executor or LocalAnalysisExecutor()
    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = AnalysisJobPayload.model_validate(raw_payload)
        resolver = LocalArtifactResolver(store, artifacts)
        with tempfile.TemporaryDirectory(prefix="cra-job-input-") as directory:
            root = Path(directory)
            repository_ref = _payload_artifact_ref(
                context, store, payload.repository_artifact, payload.repository_storage_key,
                expected_kind="repository_zip",
            )
            zip_path = resolver.materialize(
                context, repository_ref, root / "repository.zip",
            )
            validate_archive(zip_path)
            paper_path = None
            if payload.paper_artifact is not None or payload.paper_storage_key:
                paper_ref = _payload_artifact_ref(
                    context, store, payload.paper_artifact, payload.paper_storage_key,
                    expected_kind="paper_pdf",
                )
                paper_path = resolver.materialize(context, paper_ref, root / "paper.pdf")
                validate_pdf_header(paper_path)
            context.checkpoint()
            task_output = output_root / context.job.workspace_id / (context.job.project_id or "shared")
            state = await executor.run(
                run_analysis,
                zip_path,
                task_output,
                None,
                paper_path,
                text_llm_enabled=payload.text_llm_enabled,
                teaching_narrative_llm_enabled=payload.teaching_narrative_llm_enabled,
                vision_vlm_enabled=payload.vision_vlm_enabled,
                external_text_consent=payload.external_text_consent,
                external_vision_consent=payload.external_vision_consent,
                teaching_diagrams_enabled=payload.teaching_diagrams_enabled,
                image_generation_enabled=payload.image_generation_enabled,
                external_image_consent=payload.external_image_consent,
                teaching_review_vlm_enabled=payload.teaching_review_vlm_enabled,
                external_teaching_review_consent=payload.external_teaching_review_consent,
                task_id=context.job.domain_run_id,
                structured_index_enabled=True,
                repository_key=payload.repository_key,
                cancel_check=context.checkpoint_if_due,
            )
        context.checkpoint()
        result_refs: list[str] = []
        if state.get("output_dir"):
            output_path = Path(str(state["output_dir"])).resolve()
            result_refs.append(_publish_directory(
                context, store, artifacts, output_path, kind="report", role="analysis-result",
            ))
        return result_refs

    return handler


def build_index_handler(
    store: LocalControlPlaneStore, artifacts: LocalArtifactStore, output_root: Path,
    analysis_executor: LocalAnalysisExecutor | None = None,
):
    """Build a standalone index in an isolated task output without activating production input."""

    analysis = build_analysis_handler(store, artifacts, output_root, analysis_executor)

    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = IndexJobPayload.model_validate(raw_payload)
        return await analysis(context, payload.model_dump(mode="json"))

    return handler


def build_export_handler(store: LocalControlPlaneStore, artifacts: LocalArtifactStore):
    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = ArtifactListPayload.model_validate(raw_payload)
        resolver = LocalArtifactResolver(store, artifacts)
        context.checkpoint()
        with tempfile.TemporaryDirectory(prefix="cra-export-") as directory:
            archive_path = Path(directory) / "export.zip"
            manifest: list[dict[str, object]] = []
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for artifact_id in sorted(payload.artifact_ids):
                    record = _scoped_artifact(
                        context, store, artifact_id, expected_status="available",
                    )
                    path = resolver.materialize(
                        context,
                        ArtifactExecutionRef(
                            artifact_id=record.artifact_id,
                            expected_content_hash=record.content_hash,
                            expected_kind=record.kind,
                        ),
                        Path(directory) / f"{record.artifact_id}.bin",
                    )
                    archive.write(path, arcname=f"artifacts/{artifact_id}/{path.name}")
                    manifest.append({
                        "artifact_id": artifact_id,
                        "content_hash": record.content_hash,
                        "size_bytes": record.size_bytes,
                        "media_type": record.media_type,
                    })
                archive.writestr(
                    "manifest.json",
                    json.dumps({"schema_version": "2.0", "artifacts": manifest}, sort_keys=True),
                )
            context.checkpoint()
            return [_publish_file(context, store, artifacts, archive_path, kind="export")]

    return handler


def build_replay_handler(store: LocalControlPlaneStore, artifacts: LocalArtifactStore):
    """Create an immutable offline replay bundle; this handler never calls a Provider."""

    export = build_export_handler(store, artifacts)

    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = ArtifactListPayload.model_validate(raw_payload)
        return await export(context, payload.model_dump(mode="json"))

    return handler


def build_backup_handler(store: LocalControlPlaneStore, artifacts: LocalArtifactStore):
    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = BackupJobPayload.model_validate(raw_payload)
        context.checkpoint()
        with tempfile.TemporaryDirectory(prefix="cra-backup-") as directory:
            root = Path(directory)
            catalog: list[dict[str, object]] = []
            for item in store.list_available_artifacts(
                context.job.workspace_id, context.job.project_id or "",
            ):
                catalog.append({
                    "artifact_id": item.artifact_id,
                    "storage_key": item.storage_key,
                    "content_hash": item.content_hash,
                    "size_bytes": item.size_bytes,
                    "media_type": item.media_type,
                    "archive_path": f"artifacts/{item.artifact_id}/payload.bin",
                })
            manifest = {
                "schema_version": "2.0",
                "profile": "local",
                "snapshot_kind": "workspace_diagnostic_export",
                "label": payload.label,
                "workspace_id": context.job.workspace_id,
                "project_id": context.job.project_id,
                "created_at": datetime.now(UTC).isoformat(),
                "artifact_catalog": catalog,
            }
            (root / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8",
            )
            archive_path = root / "backup.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(root / "manifest.json", "manifest.json")
                for item in catalog:
                    path = artifacts.path_for_read(str(item["storage_key"]))
                    archive.write(path, str(item["archive_path"]))
            context.checkpoint()
            return [_publish_file(context, store, artifacts, archive_path, kind="backup")]

    return handler


def build_restore_handler(store: LocalControlPlaneStore, artifacts: LocalArtifactStore):
    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = RestoreJobPayload.model_validate(raw_payload)
        record = _scoped_artifact(context, store, payload.backup_artifact_id)
        if record.kind != "backup" or record.status != "available":
            raise ControlPlaneError("backup_artifact_not_available")
        source = artifacts.path_for_read(record.storage_key)
        limits = ArchiveLimits(nested_archives_allowed=True)
        validate_archive(source, limits)
        destination = artifacts.root / "restores" / context.job.job_id
        if destination.exists():
            shutil.rmtree(destination)
        extract_validated_archive(source, destination, limits)
        manifest_path = destination / "manifest.json"
        if not manifest_path.is_file():
            shutil.rmtree(destination, ignore_errors=True)
            raise ControlPlaneError("backup_manifest_invalid")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("snapshot_kind") != "workspace_diagnostic_export"
            or manifest.get("workspace_id") != context.job.workspace_id
            or manifest.get("project_id") != context.job.project_id
        ):
            shutil.rmtree(destination, ignore_errors=True)
            raise ControlPlaneError("backup_manifest_invalid")
        for item in manifest.get("artifact_catalog", []):
            archive_value = item.get("archive_path") if isinstance(item, dict) else None
            expected_hash = item.get("content_hash") if isinstance(item, dict) else None
            if not isinstance(archive_value, str) or not isinstance(expected_hash, str):
                raise ControlPlaneError("backup_manifest_invalid")
            candidate = (destination / archive_value).resolve()
            if destination.resolve() not in candidate.parents or not candidate.is_file():
                raise ControlPlaneError("backup_manifest_invalid")
            digest = _file_sha256(candidate)
            if digest != expected_hash:
                raise ControlPlaneError("backup_artifact_hash_mismatch")
        context.checkpoint()
        return [_publish_directory(
            context, store, artifacts, destination, kind="restore", role="restore-verification",
        )]

    return handler


def build_maintenance_handler(
    store: LocalControlPlaneStore, artifacts: LocalArtifactStore,
):
    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = MaintenanceJobPayload.model_validate(raw_payload)
        cutoff = datetime.now(UTC) - timedelta(seconds=payload.older_than_seconds)
        records = store.list_artifacts_for_maintenance(
            context.job.workspace_id, context.job.project_id or "",
        )
        for record in records:
            context.checkpoint()
            if record.updated_at >= cutoff:
                continue
            try:
                path = artifacts.path_for_read(record.storage_key)
            except Exception:
                continue
            if path.is_file():
                artifacts.delete(record.storage_key)
        return []

    return handler


def build_delete_handler(store: LocalControlPlaneStore, artifacts: LocalArtifactStore):
    async def handler(
        context: JobExecutionContext, raw_payload: dict[str, JsonValue],
    ) -> list[str]:
        payload = DeleteJobPayload.model_validate(raw_payload)
        context.checkpoint()
        record = _scoped_artifact(context, store, payload.artifact_id)
        if record.status == "deleted":
            return []
        if record.status != "available":
            raise ControlPlaneError("artifact_not_deletable")
        LocalArtifactResolver(store, artifacts).verify(context, ArtifactExecutionRef(
            artifact_id=record.artifact_id,
            expected_content_hash=record.content_hash,
            expected_kind=record.kind,
        ))
        context.checkpoint()
        requested = record.model_copy(update={
            "status": "deletion_requested", "updated_at": datetime.now(UTC),
        })
        store.save_artifact(requested)
        artifacts.delete(record.storage_key)
        store.save_artifact(requested.model_copy(update={
            "status": "deleted", "updated_at": datetime.now(UTC),
        }))
        return []

    return handler


def build_research_handler():
    async def handler(context: JobExecutionContext, raw_payload: dict[str, JsonValue]) -> list[str]:
        from backend.app.agents.research import api as research_api
        from backend.app.retrieval.api import get_retrieval_service

        payload = ResearchJobPayload.model_validate(raw_payload)
        coordinator = research_api._coordinator
        if coordinator is None:
            raise RuntimeError("research_runtime_unavailable")
        version_id = get_retrieval_service().read_store.resolve_version(
            payload.repo_id, payload.request.index_version_id,
        )
        run, _ = coordinator.run_store.create_run(
            repo_id=payload.repo_id, index_version_id=version_id,
            request=payload.request.model_copy(update={"index_version_id": version_id}),
            caller_scope=_caller_scope(context), idempotency_key=context.job.job_id,
        )
        coordinator.notify()
        await _wait_research(context, coordinator, run["run_id"])
        return [f"business:research_run:{run['run_id']}"]
    return handler


def build_alignment_handler():
    async def handler(context: JobExecutionContext, raw_payload: dict[str, JsonValue]) -> list[str]:
        from backend.app.alignment import api as alignment_api

        payload = AlignmentJobPayload.model_validate(raw_payload)
        service = alignment_api.get_alignment_service()
        version = service.fact_reader.resolve_version(payload.repo_id, payload.request.index_version_id)
        run, _ = service.prepare_run(
            repo_id=payload.repo_id, index_version_id=version, paper_id=payload.request.paper_id,
            request=payload.request.model_copy(update={"index_version_id": version}).model_dump(mode="json"),
            caller_scope=_caller_scope(context), idempotency_key=context.job.job_id,
            retry_of_run_id=payload.request.retry_of_run_id,
        )
        if alignment_api._coordinator is None:
            raise RuntimeError("alignment_runtime_unavailable")
        alignment_api._coordinator.notify()
        await _wait_alignment(context, alignment_api, run["run_id"])
        return [f"business:alignment_run:{run['run_id']}"]
    return handler


def build_evaluation_handler():
    async def handler(context: JobExecutionContext, raw_payload: dict[str, JsonValue]) -> list[str]:
        from backend.app.evaluation import api as evaluation_api

        payload = EvaluationJobPayload.model_validate(raw_payload)
        if payload.request.mode == "live_experiment":
            raise ValueError("live_evaluation_requires_explicit_v2_consent")
        run = evaluation_api.get_evaluation_service().prepare_run(
            payload.request, caller_scope_hash=_caller_scope(context),
        )
        if evaluation_api._coordinator is None:
            raise RuntimeError("evaluation_runtime_unavailable")
        evaluation_api._coordinator.notify()
        await _wait_evaluation(context, evaluation_api, run.run_id)
        return [f"business:evaluation_run:{run.run_id}"]
    return handler


async def _wait_research(context: JobExecutionContext, coordinator, run_id: str) -> None:
    while True:
        context.checkpoint_if_due()
        run = coordinator.run_store.get_run(run_id)
        if run["status"] in {"completed", "partial", "failed", "cancelled", "interrupted"}:
            if run["status"] == "failed":
                raise RuntimeError("research_run_failed")
            return
        if context.cancel_requested():
            coordinator.run_store.request_cancel(run_id)
        await asyncio.sleep(0.2)


async def _wait_alignment(context: JobExecutionContext, alignment_api, run_id: str) -> None:
    while True:
        context.checkpoint_if_due()
        run = alignment_api.get_alignment_store().get_run(run_id)
        if run["status"] in {"completed", "partial", "failed", "cancelled", "abandoned"}:
            if run["status"] == "failed":
                raise RuntimeError("alignment_run_failed")
            return
        if context.cancel_requested():
            alignment_api.get_alignment_store().request_cancel(run_id)
        await asyncio.sleep(0.2)


async def _wait_evaluation(context: JobExecutionContext, evaluation_api, run_id: str) -> None:
    while True:
        context.checkpoint_if_due()
        run = evaluation_api.get_evaluation_store().get_run(run_id)
        if run.status in {"completed", "partial", "failed", "cancelled"}:
            if run.status == "failed":
                raise RuntimeError("evaluation_run_failed")
            return
        if context.cancel_requested():
            evaluation_api.get_evaluation_store().request_cancel(run_id)
        await asyncio.sleep(0.2)


def _caller_scope(context: JobExecutionContext) -> str:
    return f"control:{context.job.workspace_id}:{context.job.project_id or 'shared'}"


def _scoped_artifact(
    context: JobExecutionContext, store: LocalControlPlaneStore, artifact_id: str,
    *, expected_status: str | None = None, expected_kind: str | None = None,
) -> ArtifactRecord:
    record = store.get_artifact(artifact_id)
    if (
        record.workspace_id != context.job.workspace_id
        or record.project_id != (context.job.project_id or "")
    ):
        raise ControlPlaneError("artifact_not_found")
    if expected_status is not None and record.status != expected_status:
        raise ControlPlaneError("artifact_not_available")
    if expected_kind is not None and record.kind != expected_kind:
        raise ControlPlaneError("artifact_kind_mismatch")
    return record


class LocalArtifactResolver:
    """Resolve and hash-check Local artifacts at the execution boundary."""

    def __init__(self, store: LocalControlPlaneStore, artifacts: LocalArtifactStore) -> None:
        self.store = store
        self.artifacts = artifacts

    def verify(
        self, context: JobExecutionContext, reference: ArtifactExecutionRef,
    ) -> ArtifactRecord:
        return self._verify(context.job, reference, context.checkpoint_if_due)

    def verify_for_job(
        self, job: JobRecord, reference: ArtifactExecutionRef,
    ) -> ArtifactRecord:
        return self._verify(job, reference, None)

    def _verify(self, job, reference, checkpoint) -> ArtifactRecord:
        record = self.store.get_artifact(reference.artifact_id)
        if (
            record.workspace_id != job.workspace_id
            or record.project_id != (job.project_id or "")
        ):
            raise ControlPlaneError("artifact_not_found")
        if record.status != "available":
            raise ControlPlaneError("artifact_not_available")
        if record.kind != reference.expected_kind:
            raise ControlPlaneError("artifact_kind_mismatch")
        if record.content_hash != reference.expected_content_hash:
            raise ControlPlaneError("artifact_hash_mismatch")
        digest = hashlib.sha256()
        size = 0
        try:
            with self.artifacts.open(record.storage_key) as source:
                while chunk := source.read(1024 * 1024):
                    if checkpoint is not None:
                        checkpoint()
                    size += len(chunk)
                    digest.update(chunk)
        except (ArtifactSecurityError, OSError) as exc:
            raise ControlPlaneError("artifact_not_available") from exc
        if digest.hexdigest() != record.content_hash or size != record.size_bytes:
            raise ControlPlaneError("artifact_hash_mismatch")
        return record

    def materialize(
        self, context: JobExecutionContext, reference: ArtifactExecutionRef, destination: Path,
    ) -> Path:
        record = self._verify(context.job, reference, context.checkpoint_if_due)
        return self._copy_verified(
            record, reference, destination, context.checkpoint_if_due,
        )

    def materialize_for_job(
        self, job: JobRecord, reference: ArtifactExecutionRef, destination: Path,
    ) -> Path:
        record = self.verify_for_job(job, reference)
        return self._copy_verified(record, reference, destination, None)

    def _copy_verified(self, record, reference, destination, checkpoint) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with self.artifacts.open(record.storage_key) as source, destination.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                if checkpoint is not None:
                    checkpoint()
                size += len(chunk)
                digest.update(chunk)
                target.write(chunk)
        if digest.hexdigest() != reference.expected_content_hash or size != record.size_bytes:
            destination.unlink(missing_ok=True)
            raise ControlPlaneError("artifact_hash_mismatch")
        return destination


def _payload_artifact_ref(
    context: JobExecutionContext,
    store: LocalControlPlaneStore,
    reference: ArtifactExecutionRef | None,
    legacy_storage_key: str | None,
    *,
    expected_kind: str,
) -> ArtifactExecutionRef:
    if reference is not None:
        if legacy_storage_key is not None:
            raise ControlPlaneError("job_payload_invalid")
        return reference
    if not legacy_storage_key:
        raise ControlPlaneError("job_payload_invalid")
    record = store.find_scoped_artifact_by_storage_key(
        context.job.workspace_id, context.job.project_id or "", legacy_storage_key,
    )
    if record.kind != expected_kind:
        raise ControlPlaneError("legacy_artifact_payload_unverifiable")
    return ArtifactExecutionRef(
        artifact_id=record.artifact_id,
        expected_content_hash=record.content_hash,
        expected_kind=record.kind,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_directory(
    context: JobExecutionContext,
    store: LocalControlPlaneStore,
    artifacts: LocalArtifactStore,
    directory: Path,
    *,
    kind: str,
    role: str,
) -> str:
    context.checkpoint()
    if not directory.is_dir():
        raise ControlPlaneError("result_directory_missing")
    with tempfile.TemporaryDirectory(prefix="cra-result-") as temporary:
        archive_path = Path(temporary) / f"{role}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob("*")):
                context.checkpoint_if_due()
                if path.is_symlink():
                    raise ControlPlaneError("result_symlink_rejected")
                if path.is_file():
                    archive.write(path, path.relative_to(directory).as_posix())
        return _publish_file(context, store, artifacts, archive_path, kind=kind)


def _publish_file(
    context: JobExecutionContext,
    store: LocalControlPlaneStore,
    artifacts: LocalArtifactStore,
    path: Path,
    *,
    kind: str,
) -> str:
    context.checkpoint()
    artifact_id = f"artifact_{uuid4().hex}"
    with path.open("rb") as source:
        staging_key, digest, size = artifacts.stage(artifact_id, source)
    suffix = path.suffix.casefold() or ".bin"
    storage_key = (
        f"{context.job.workspace_id}/{context.job.project_id or 'shared'}/generated/"
        f"{artifact_id}{suffix}"
    )
    now = datetime.now(UTC)
    record = ArtifactRecord(
        artifact_id=artifact_id,
        workspace_id=context.job.workspace_id,
        project_id=context.job.project_id or "",
        kind=kind,
        status="staging",
        storage_key=staging_key,
        content_hash=digest,
        size_bytes=size,
        media_type="application/zip" if suffix == ".zip" else "application/octet-stream",
        created_at=now,
        updated_at=now,
    )
    persisted: ArtifactRecord | None = None
    try:
        context.checkpoint()
        store.save_artifact(record)
        persisted = record
        quarantined = record.model_copy(update={"status": "quarantined", "updated_at": datetime.now(UTC)})
        store.save_artifact(quarantined)
        persisted = quarantined
        validating = quarantined.model_copy(update={"status": "validating", "updated_at": datetime.now(UTC)})
        store.save_artifact(validating)
        persisted = validating
        context.checkpoint()
        artifacts.finalize(staging_key, storage_key, digest)
        available = validating.model_copy(update={
            "status": "available", "storage_key": storage_key, "updated_at": datetime.now(UTC),
        })
        store.save_artifact(available)
    except BaseException:
        artifacts.delete(staging_key)
        if persisted is not None and persisted.status in {"staging", "quarantined", "validating"}:
            try:
                store.save_artifact(persisted.model_copy(update={
                    "status": "orphaned",
                    "error_code": "artifact_publish_incomplete",
                    "updated_at": datetime.now(UTC),
                }))
            except Exception:
                pass
        raise
    return artifact_id
