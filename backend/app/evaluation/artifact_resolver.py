from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from backend.app.evaluation.schemas import EvaluationArtifactRef


@dataclass(frozen=True, slots=True)
class EvaluationAccessContext:
    caller_scope_hash: str
    repository_ids: frozenset[str] = frozenset()
    local_admin: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    content: bytes
    media_type: str
    content_hash: str


class ArtifactResolverError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class EvaluationArtifactResolver(Protocol):
    def resolve(
        self, artifact_ref: EvaluationArtifactRef, access_context: EvaluationAccessContext
    ) -> ResolvedArtifact: ...


ArtifactLoader = Callable[[str, EvaluationAccessContext], bytes]


class ControlledArtifactResolver:
    """Resolver for registered stores and a sandboxed fixture root only."""

    def __init__(self, *, fixture_root: str | Path | None = None) -> None:
        self.fixture_root = Path(fixture_root).resolve() if fixture_root else None
        self._loaders: dict[str, ArtifactLoader] = {}

    def register(self, scheme: str, loader: ArtifactLoader) -> None:
        if not scheme or any(char in scheme for char in "/:."):
            raise ValueError("invalid artifact resolver scheme")
        self._loaders[scheme] = loader

    def resolve(
        self, artifact_ref: EvaluationArtifactRef, access_context: EvaluationAccessContext
    ) -> ResolvedArtifact:
        if artifact_ref.availability_status != "available":
            raise ArtifactResolverError(f"artifact_{artifact_ref.availability_status}")
        if artifact_ref.repo_id and not (
            access_context.local_admin or artifact_ref.repo_id in access_context.repository_ids
        ):
            raise ArtifactResolverError("artifact_access_denied")
        scheme, locator = artifact_ref.storage_locator.split(":", 1)
        if scheme == "fixture":
            content = self._load_fixture(locator)
        else:
            loader = self._loaders.get(scheme)
            if loader is None:
                raise ArtifactResolverError("artifact_locator_scheme_not_allowed")
            content = loader(locator, access_context)
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact_ref.content_hash:
            raise ArtifactResolverError("artifact_hash_mismatch")
        if artifact_ref.size_bytes is not None and len(content) != artifact_ref.size_bytes:
            raise ArtifactResolverError("artifact_size_mismatch")
        return ResolvedArtifact(content, artifact_ref.media_type, digest)

    def _load_fixture(self, locator: str) -> bytes:
        if self.fixture_root is None:
            raise ArtifactResolverError("fixture_root_unavailable")
        relative = Path(locator.lstrip("/"))
        target = (self.fixture_root / relative).resolve()
        try:
            target.relative_to(self.fixture_root)
        except ValueError as exc:
            raise ArtifactResolverError("artifact_path_escape") from exc
        if not target.is_file():
            raise ArtifactResolverError("artifact_missing")
        return target.read_bytes()
