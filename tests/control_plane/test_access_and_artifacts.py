from __future__ import annotations

import io
import zipfile

import pytest

from backend.app.control_plane.access import AccessContext, AccessDeniedError, DefaultAccessPolicy
from backend.app.control_plane.artifacts import (
    ArchiveLimits, ArtifactSecurityError, LocalArtifactStore, validate_archive,
    validate_git_commit_sha, validate_git_url,
)


def test_workspace_member_cannot_read_unassigned_project():
    context = AccessContext("user", "w", "p", "member", None)
    with pytest.raises(AccessDeniedError):
        DefaultAccessPolicy().require(context, "artifact.read")


def test_project_reviewer_can_review_but_cannot_change_provider_secret():
    context = AccessContext("user", "w", "p", "member", "reviewer")
    DefaultAccessPolicy().require(context, "alignment.review")
    with pytest.raises(AccessDeniedError):
        DefaultAccessPolicy().require(context, "provider.manage")


@pytest.mark.parametrize("role", ["project_owner", "editor", "reviewer", "viewer"])
def test_project_roles_can_read_results(role):
    context = AccessContext("user", "w", "p", "member", role)
    DefaultAccessPolicy().require(context, "result.read")


def test_workspace_viewer_cannot_read_gold_by_default():
    context = AccessContext("user", "w", None, "viewer")
    with pytest.raises(AccessDeniedError):
        DefaultAccessPolicy().require(context, "gold.read")


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members:
            archive.writestr(name, value)


def test_zip_slip_is_rejected(tmp_path):
    path = tmp_path / "bad.zip"
    _zip(path, [("../escape.py", "x")])
    with pytest.raises(ArtifactSecurityError, match="archive_path_escape"):
        validate_archive(path)


def test_symlink_escape_is_rejected(tmp_path):
    path = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link")
    info.external_attr = (0o120777 << 16)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, "outside")
    with pytest.raises(ArtifactSecurityError, match="archive_special_file_rejected"):
        validate_archive(path)


def test_archive_bomb_is_rejected(tmp_path):
    path = tmp_path / "bomb.zip"
    _zip(path, [("large.txt", "0" * 10_000)])
    with pytest.raises(ArtifactSecurityError):
        validate_archive(path, ArchiveLimits(extracted_bytes=100))


def test_git_file_protocol_is_rejected():
    with pytest.raises(ArtifactSecurityError, match="git_protocol_rejected"):
        validate_git_url("file:///tmp/repo")


def test_git_commit_must_be_fixed_sha():
    with pytest.raises(ArtifactSecurityError, match="git_commit_sha_required"):
        validate_git_commit_sha("main")


def test_local_artifact_store_hash_and_path_controls(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    staging, digest, size = store.stage("a", io.BytesIO(b"content"))
    assert size == 7
    store.finalize(staging, "workspace/project/a", digest)
    assert store.open("workspace/project/a").read() == b"content"
    with pytest.raises(ArtifactSecurityError):
        store.open("../outside")
