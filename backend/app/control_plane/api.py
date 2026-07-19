from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .access import AccessContext, AccessDeniedError, DefaultAccessPolicy
from .auth import AccessPrincipal, AuthenticationError, LocalIdentityService
from .jobs import JobRequest
from .store import ControlPlaneError, LocalControlPlaneStore
from .artifacts import ArtifactSecurityError, LocalArtifactStore, validate_archive, validate_pdf_header
from .schemas import ArtifactRecord
from datetime import UTC, datetime


router = APIRouter(prefix="/api/v2", tags=["platform-v2"])


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictRequest):
    username: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


class LoginRequest(RegisterRequest):
    pass


class PasswordChangeRequest(StrictRequest):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class WorkspaceCreateRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=200)


class ProjectCreateRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=200)


class JobCreateRequest(StrictRequest):
    job_type: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=256)


def _runtime(request: Request):
    runtime = getattr(request.app.state, "control_plane_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail={"error_code": "control_plane_unavailable"})
    return runtime


def _identity(request: Request) -> LocalIdentityService:
    identity = _runtime(request).identity
    if not isinstance(identity, LocalIdentityService):
        raise HTTPException(status_code=503, detail={"error_code": "identity_unavailable"})
    return identity


def _principal(
    request: Request, authorization: Annotated[str | None, Header()] = None,
) -> AccessPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error_code": "authentication_required"})
    try:
        return _identity(request).verify_access(authorization[7:])
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail={"error_code": exc.code}) from exc


@router.get("/health")
def v2_health(request: Request) -> dict[str, str]:
    runtime = _runtime(request)
    return {"status": "ok", "profile": runtime.settings.profile.value, "api_contract_version": "2"}


@router.post("/auth/bootstrap", status_code=201)
def register(
    body: RegisterRequest, request: Request,
    bootstrap_token: Annotated[str | None, Header(alias="X-Bootstrap-Token")] = None,
) -> dict[str, str]:
    if not bootstrap_token:
        raise HTTPException(status_code=403, detail={"error_code": "bootstrap_invalid"})
    try:
        user_id = _identity(request).bootstrap_owner(bootstrap_token, body.username, body.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=400, detail={"error_code": exc.code}) from exc
    return {"user_id": user_id}


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    try:
        tokens = _identity(request).login(body.username, body.password, user_agent=request.headers.get("user-agent", ""))
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail={"error_code": exc.code}) from exc
    _set_session_cookies(
        response, tokens.refresh_token, tokens.csrf_token, secure=_secure_cookies(),
    )
    return {"access_token": tokens.access_token, "token_type": "bearer", "session_id": tokens.session_id}


@router.post("/auth/refresh")
def refresh(
    request: Request,
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias="cra_refresh")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias="cra_csrf")] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, str]:
    if not refresh_token or not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail={"error_code": "csrf_required"})
    try:
        tokens = _identity(request).refresh(refresh_token, csrf_header)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail={"error_code": exc.code}) from exc
    _set_session_cookies(
        response, tokens.refresh_token, tokens.csrf_token, secure=_secure_cookies(),
    )
    return {"access_token": tokens.access_token, "token_type": "bearer", "session_id": tokens.session_id}


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
    csrf_cookie: Annotated[str | None, Cookie(alias="cra_csrf")] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail={"error_code": "csrf_required"})
    _identity(request).logout(principal.session_id)
    response.delete_cookie("cra_refresh")
    response.delete_cookie("cra_csrf")


@router.get("/auth/sessions")
def list_sessions(
    request: Request, principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, list[dict[str, str | None]]]:
    return {"sessions": _identity(request).list_sessions(principal.user_id)}


@router.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> None:
    try:
        _identity(request).revoke_session(principal.user_id, session_id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "session_not_found"}) from exc


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordChangeRequest, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> None:
    try:
        _identity(request).change_password(
            principal.user_id, body.current_password, body.new_password,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=400, detail={"error_code": exc.code}) from exc


@router.post("/workspaces", status_code=201)
def create_workspace(
    body: WorkspaceCreateRequest, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, str]:
    workspace_id = f"ws_{uuid4().hex}"
    store = _local_store(request)
    store.create_workspace(workspace_id, body.name, principal.user_id)
    return {"workspace_id": workspace_id}


@router.get("/workspaces")
def list_workspaces(
    request: Request, principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, list[dict[str, str]]]:
    return {"items": _local_store(request).list_workspaces_for_user(principal.user_id)}


@router.post("/workspaces/{workspace_id}/projects", status_code=201)
def create_project(
    workspace_id: str, body: ProjectCreateRequest, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, str]:
    context = _access_context(request, principal, workspace_id, None)
    DefaultAccessPolicy().require(context, "project.manage")
    project_id = f"project_{uuid4().hex}"
    _local_store(request).create_project(project_id, workspace_id, body.name, principal.user_id)
    return {"project_id": project_id}


@router.get("/workspaces/{workspace_id}/projects")
def list_projects(
    workspace_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, list[dict[str, str]]]:
    try:
        items = _local_store(request).list_projects_for_user(principal.user_id, workspace_id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "resource_not_found"}) from exc
    return {"items": items}


@router.post("/workspaces/{workspace_id}/projects/{project_id}/jobs", status_code=202)
async def submit_job(
    workspace_id: str, project_id: str, body: JobCreateRequest, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, str]:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "job.create")
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail={"error_code": "access_denied"}) from exc
    runtime = _runtime(request)
    payload = dict(body.payload)
    if body.job_type in {"analysis", "indexing"}:
        repository_artifact_id = payload.pop("repository_artifact_id", None)
        if not isinstance(repository_artifact_id, str):
            raise HTTPException(status_code=400, detail={"error_code": "repository_artifact_required"})
        try:
            repository = _local_store(request).get_artifact(repository_artifact_id)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=404, detail={"error_code": "artifact_not_found"}) from exc
        if (
            repository.workspace_id != workspace_id or repository.project_id != project_id
            or repository.status != "available" or repository.kind != "repository_zip"
        ):
            raise HTTPException(status_code=409, detail={"error_code": "artifact_not_available"})
        payload["repository_storage_key"] = repository.storage_key
        paper_artifact_id = payload.pop("paper_artifact_id", None)
        if paper_artifact_id is not None:
            if not isinstance(paper_artifact_id, str):
                raise HTTPException(status_code=400, detail={"error_code": "paper_artifact_invalid"})
            try:
                paper = _local_store(request).get_artifact(paper_artifact_id)
            except ControlPlaneError as exc:
                raise HTTPException(status_code=404, detail={"error_code": "artifact_not_found"}) from exc
            if (
                paper.workspace_id != workspace_id or paper.project_id != project_id
                or paper.status != "available" or paper.kind != "paper_pdf"
            ):
                raise HTTPException(status_code=409, detail={"error_code": "artifact_not_available"})
            payload["paper_storage_key"] = paper.storage_key
    try:
        handle = await runtime.jobs.submit(JobRequest(
            workspace_id=workspace_id, project_id=project_id,
            job_type=body.job_type,  # validated by the strict JobRequest/store boundary
            queue_name=f"cra.{body.job_type}", payload=payload,
            idempotency_key=body.idempotency_key, actor_id_hash=principal.user_id,
        ))
    except (ControlPlaneError, ValueError) as exc:
        code = exc.code if isinstance(exc, ControlPlaneError) else "invalid_job_request"
        raise HTTPException(status_code=400, detail={"error_code": code}) from exc
    return {"job_id": handle.job_id, "attempt_id": handle.attempt_id, "domain_run_id": handle.domain_run_id}


@router.post("/workspaces/{workspace_id}/projects/{project_id}/artifacts", status_code=201)
def upload_artifact(
    workspace_id: str, project_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
    artifact: UploadFile = File(...),
) -> dict:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "artifact.create")
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail={"error_code": "access_denied"}) from exc
    suffix = (artifact.filename or "").lower()
    if suffix.endswith(".zip"):
        kind, media_type = "repository_zip", "application/zip"
    elif suffix.endswith(".pdf"):
        kind, media_type = "paper_pdf", "application/pdf"
    else:
        raise HTTPException(status_code=400, detail={"error_code": "artifact_type_rejected"})
    runtime = _runtime(request)
    artifacts = runtime.artifacts
    if not isinstance(artifacts, LocalArtifactStore):
        raise HTTPException(status_code=503, detail={"error_code": "artifact_store_unavailable"})
    artifact_id = f"artifact_{uuid4().hex}"
    max_bytes = 100 * 1024 * 1024 if kind == "repository_zip" else 50 * 1024 * 1024
    try:
        staging_key, digest, size = artifacts.stage(
            artifact_id, artifact.file, max_bytes=max_bytes,
        )
    except ArtifactSecurityError as exc:
        raise HTTPException(status_code=400, detail={"error_code": exc.code}) from exc
    now = datetime.now(UTC)
    record = ArtifactRecord(
        artifact_id=artifact_id, workspace_id=workspace_id, project_id=project_id,
        kind=kind, status="staging", storage_key=staging_key,
        content_hash=digest, size_bytes=size, media_type=media_type,
        created_at=now, updated_at=now,
    )
    store = _local_store(request)
    store.save_artifact(record)
    quarantined = record.model_copy(update={"status": "quarantined", "updated_at": datetime.now(UTC)})
    store.save_artifact(quarantined)
    validating = quarantined.model_copy(update={"status": "validating", "updated_at": datetime.now(UTC)})
    store.save_artifact(validating)
    try:
        path = artifacts.path_for_read(staging_key)
        validate_archive(path) if kind == "repository_zip" else validate_pdf_header(path)
        storage_key = f"{workspace_id}/{project_id}/{artifact_id}{'.zip' if kind == 'repository_zip' else '.pdf'}"
        artifacts.finalize(staging_key, storage_key, digest)
        available = validating.model_copy(update={
            "status": "available", "storage_key": storage_key, "updated_at": datetime.now(UTC),
        })
        store.save_artifact(available)
    except ArtifactSecurityError as exc:
        artifacts.delete(staging_key)
        rejected = validating.model_copy(update={
            "status": "rejected", "error_code": exc.code, "updated_at": datetime.now(UTC),
        })
        store.save_artifact(rejected)
        raise HTTPException(status_code=400, detail={"error_code": exc.code}) from exc
    except Exception as exc:
        artifacts.delete(staging_key)
        orphaned = validating.model_copy(update={
            "status": "orphaned", "error_code": "artifact_finalize_failed",
            "updated_at": datetime.now(UTC),
        })
        store.save_artifact(orphaned)
        raise HTTPException(
            status_code=503, detail={"error_code": "artifact_finalize_failed"},
        ) from exc
    return _public_artifact(available)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/artifacts")
def list_artifacts(
    workspace_id: str, project_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)], limit: int = 100,
) -> dict:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "artifact.read")
    except AccessDeniedError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "resource_not_found"}) from exc
    return {"items": [_public_artifact(item) for item in _local_store(request).list_artifacts(
        workspace_id, project_id, limit=limit,
    )]}


@router.get("/workspaces/{workspace_id}/projects/{project_id}/artifacts/{artifact_id}")
def get_artifact(
    workspace_id: str, project_id: str, artifact_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict:
    return _public_artifact(_scoped_readable_artifact(
        request, principal, workspace_id, project_id, artifact_id,
    ))


@router.get("/workspaces/{workspace_id}/projects/{project_id}/artifacts/{artifact_id}/content")
def download_artifact(
    workspace_id: str, project_id: str, artifact_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> StreamingResponse:
    artifact = _scoped_readable_artifact(
        request, principal, workspace_id, project_id, artifact_id,
    )
    if artifact.status != "available":
        raise HTTPException(status_code=409, detail={"error_code": "artifact_not_available"})
    store = _runtime(request).artifacts
    if not isinstance(store, LocalArtifactStore):
        raise HTTPException(status_code=503, detail={"error_code": "artifact_store_unavailable"})
    try:
        source = store.open(artifact.storage_key)
    except ArtifactSecurityError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "artifact_not_found"}) from exc
    return StreamingResponse(
        _stream_binary(source), media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.artifact_id}"',
            "X-Content-SHA256": artifact.content_hash,
            "Content-Length": str(artifact.size_bytes),
        },
    )


@router.get("/workspaces/{workspace_id}/projects/{project_id}/jobs/{job_id}")
async def get_job(
    workspace_id: str, project_id: str, job_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "result.read")
        job = await _runtime(request).jobs.get_status(job_id)
    except (AccessDeniedError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"}) from exc
    if job.workspace_id != workspace_id or job.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return job.model_dump(mode="json")


@router.get("/workspaces/{workspace_id}/projects/{project_id}/jobs")
def list_jobs(
    workspace_id: str, project_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
    limit: int = 100,
) -> dict:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "result.read")
    except AccessDeniedError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "resource_not_found"}) from exc
    bounded = max(1, min(limit, 200))
    return {
        "items": [item.model_dump(mode="json") for item in _local_store(request).list_jobs(
            workspace_id, project_id, limit=bounded,
        )]
    }


@router.get("/workspaces/{workspace_id}/projects/{project_id}/jobs/{job_id}/attempts")
def list_job_attempts(
    workspace_id: str, project_id: str, job_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "result.read")
        job = _local_store(request).get_job(job_id)
    except (AccessDeniedError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"}) from exc
    if job.workspace_id != workspace_id or job.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"items": [
        item.model_dump(mode="json") for item in _local_store(request).list_attempts(job_id)
    ]}


@router.post("/workspaces/{workspace_id}/projects/{project_id}/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(
    workspace_id: str, project_id: str, job_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "job.cancel")
        job = await _runtime(request).jobs.get_status(job_id)
        if job.workspace_id != workspace_id or job.project_id != project_id:
            raise ControlPlaneError("job_not_found")
        await _runtime(request).jobs.cancel(job_id)
    except (AccessDeniedError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"}) from exc
    return (await _runtime(request).jobs.get_status(job_id)).model_dump(mode="json")


@router.post("/workspaces/{workspace_id}/projects/{project_id}/jobs/{job_id}/retry", status_code=202)
async def retry_job(
    workspace_id: str, project_id: str, job_id: str, request: Request,
    principal: Annotated[AccessPrincipal, Depends(_principal)],
) -> dict[str, str]:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "job.retry")
        job = await _runtime(request).jobs.get_status(job_id)
        if job.workspace_id != workspace_id or job.project_id != project_id:
            raise ControlPlaneError("job_not_found")
        handle = await _runtime(request).jobs.retry(job_id)
    except (AccessDeniedError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"}) from exc
    return {
        "job_id": handle.job_id, "attempt_id": handle.attempt_id,
        "domain_run_id": handle.domain_run_id,
    }


def _access_context(
    request: Request, principal: AccessPrincipal, workspace_id: str, project_id: str | None,
) -> AccessContext:
    try:
        workspace, project = _local_store(request).get_memberships(principal.user_id, workspace_id, project_id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "resource_not_found"}) from exc
    return AccessContext(
        actor_id=principal.user_id, workspace_id=workspace_id, project_id=project_id,
        workspace_role=workspace.role, project_role=project.role if project else None,
        explicit_permissions=_local_store(request).get_explicit_permissions(
            principal.user_id, workspace_id, project_id,
        ),
    )


def _local_store(request: Request) -> LocalControlPlaneStore:
    store = _runtime(request).store
    if not isinstance(store, LocalControlPlaneStore):
        raise HTTPException(status_code=503, detail={"error_code": "team_store_not_configured"})
    return store


def _scoped_readable_artifact(
    request: Request,
    principal: AccessPrincipal,
    workspace_id: str,
    project_id: str,
    artifact_id: str,
) -> ArtifactRecord:
    context = _access_context(request, principal, workspace_id, project_id)
    try:
        DefaultAccessPolicy().require(context, "artifact.read")
        artifact = _local_store(request).get_artifact(artifact_id)
    except (AccessDeniedError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail={"error_code": "artifact_not_found"}) from exc
    if artifact.workspace_id != workspace_id or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error_code": "artifact_not_found"})
    return artifact


def _stream_binary(source):
    try:
        while chunk := source.read(1024 * 1024):
            yield chunk
    finally:
        source.close()


def _public_artifact(artifact: ArtifactRecord) -> dict:
    value = artifact.model_dump(mode="json")
    value.pop("storage_key", None)
    return value


def _set_session_cookies(
    response: Response, refresh_token: str, csrf_token: str, *, secure: bool,
) -> None:
    response.set_cookie(
        "cra_refresh", refresh_token, httponly=True, secure=secure, samesite="lax",
        max_age=30 * 24 * 3600, path="/api/v2/auth",
    )
    response.set_cookie(
        "cra_csrf", csrf_token, httponly=False, secure=secure, samesite="lax",
        max_age=30 * 24 * 3600, path="/api/v2/auth",
    )


def _secure_cookies() -> bool:
    import os

    config_path = os.getenv("CRA_CONFIG_PATH")
    if not config_path:
        return True
    from backend.app.config.application import ApplicationConfig

    return ApplicationConfig.load(config_path).security.secure_cookies
