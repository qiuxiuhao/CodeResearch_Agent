from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import socket
import stat
import zipfile
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol
from urllib.parse import urlparse
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    compressed_bytes: int = 100 * 1024 * 1024
    extracted_bytes: int = 2 * 1024 * 1024 * 1024
    compression_ratio: float = 100.0
    file_count: int = 50_000
    directory_depth: int = 32
    filename_bytes: int = 255
    nested_archives_allowed: bool = False


class ArtifactSecurityError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ArtifactStore(Protocol):
    def stage(
        self, artifact_id: str, source: BinaryIO, *, max_bytes: int | None = None,
    ) -> tuple[str, str, int]: ...
    def finalize(self, staging_key: str, storage_key: str, expected_hash: str) -> None: ...
    def delete(self, storage_key: str) -> None: ...
    def open(self, storage_key: str) -> BinaryIO: ...


class LocalArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.staging_root = self.root / ".staging"
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def stage(
        self, artifact_id: str, source: BinaryIO, *, max_bytes: int | None = None,
    ) -> tuple[str, str, int]:
        staging_key = f".staging/{artifact_id}-{uuid4().hex}"
        destination = self._resolve(staging_key)
        digest = hashlib.sha256()
        size = 0
        try:
            with destination.open("xb") as handle:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise ArtifactSecurityError("artifact_size_exceeded")
                    digest.update(chunk)
                    handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return staging_key, digest.hexdigest(), size

    def finalize(self, staging_key: str, storage_key: str, expected_hash: str) -> None:
        source = self._resolve(staging_key)
        destination = self._resolve(storage_key)
        if not source.is_file() or _file_hash(source) != expected_hash:
            raise ArtifactSecurityError("artifact_hash_mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        if path.exists():
            path.unlink()

    def open(self, storage_key: str) -> BinaryIO:
        return self._resolve(storage_key).open("rb")

    def path_for_read(self, storage_key: str) -> Path:
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ArtifactSecurityError("artifact_not_available")
        return path

    def _resolve(self, storage_key: str) -> Path:
        if not storage_key or storage_key.startswith(("/", "~")):
            raise ArtifactSecurityError("invalid_storage_key")
        candidate = (self.root / storage_key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ArtifactSecurityError("artifact_path_escape")
        return candidate


class S3ArtifactStore:
    """S3-compatible staged object store; metadata is still authoritative in PostgreSQL."""

    def __init__(
        self, endpoint_url: str, bucket: str, *, access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("team profile requires boto3") from exc
        self.bucket = bucket
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def stage(
        self, artifact_id: str, source: BinaryIO, *, max_bytes: int | None = None,
    ) -> tuple[str, str, int]:
        key = self._key(f"staging/{artifact_id}-{uuid4().hex}")
        digest = hashlib.sha256()
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as buffer:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise ArtifactSecurityError("artifact_size_exceeded")
                digest.update(chunk)
                buffer.write(chunk)
            buffer.seek(0)
            content_hash = digest.hexdigest()
            self.client.upload_fileobj(
                buffer, self.bucket, key, ExtraArgs={"Metadata": {"sha256": content_hash}},
            )
        return key, content_hash, size

    def finalize(self, staging_key: str, storage_key: str, expected_hash: str) -> None:
        source_key = self._key(staging_key)
        target_key = self._key(storage_key)
        metadata = self.client.head_object(Bucket=self.bucket, Key=source_key).get("Metadata", {})
        if metadata.get("sha256") != expected_hash:
            raise ArtifactSecurityError("artifact_hash_mismatch")
        self.client.copy_object(
            Bucket=self.bucket, Key=target_key,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            Metadata={"sha256": expected_hash}, MetadataDirective="REPLACE",
        )
        self.client.delete_object(Bucket=self.bucket, Key=source_key)

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(storage_key))

    def open(self, storage_key: str) -> BinaryIO:
        buffer = io.BytesIO()
        self.client.download_fileobj(self.bucket, self._key(storage_key), buffer)
        buffer.seek(0)
        return buffer

    @staticmethod
    def _key(value: str) -> str:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or not value:
            raise ArtifactSecurityError("invalid_storage_key")
        return str(pure)


def validate_archive(path: str | Path, limits: ArchiveLimits | None = None) -> None:
    limits = limits or ArchiveLimits()
    archive_path = Path(path)
    if archive_path.stat().st_size > limits.compressed_bytes:
        raise ArtifactSecurityError("archive_compressed_size_exceeded")
    if not zipfile.is_zipfile(archive_path):
        raise ArtifactSecurityError("archive_invalid")
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > limits.file_count:
            raise ArtifactSecurityError("archive_file_count_exceeded")
        for member in members:
            name = member.filename
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\x00" in name:
                raise ArtifactSecurityError("archive_path_escape")
            if len(pure.parts) > limits.directory_depth:
                raise ArtifactSecurityError("archive_depth_exceeded")
            if any(len(part.encode("utf-8")) > limits.filename_bytes for part in pure.parts):
                raise ArtifactSecurityError("archive_filename_too_long")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
                raise ArtifactSecurityError("archive_special_file_rejected")
            total += member.file_size
            if total > limits.extracted_bytes:
                raise ArtifactSecurityError("archive_extracted_size_exceeded")
            compressed = max(member.compress_size, 1)
            if member.file_size / compressed > limits.compression_ratio:
                raise ArtifactSecurityError("archive_compression_ratio_exceeded")
            if not limits.nested_archives_allowed and pure.suffix.lower() in {
                ".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar",
            }:
                raise ArtifactSecurityError("nested_archive_rejected")


def extract_validated_archive(
    path: str | Path, destination: str | Path, limits: ArchiveLimits | None = None,
) -> None:
    validate_archive(path, limits)
    destination_path = Path(destination).resolve()
    destination_path.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                target = (destination_path / member.filename).resolve()
                if destination_path not in target.parents and target != destination_path:
                    raise ArtifactSecurityError("archive_path_escape")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except Exception:
        shutil.rmtree(destination_path, ignore_errors=True)
        raise


def validate_git_url(url: str, *, allowed_hosts: frozenset[str] = frozenset()) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "ssh"}:
        raise ArtifactSecurityError("git_protocol_rejected")
    if parsed.scheme == "ssh" and (not parsed.hostname or parsed.hostname not in allowed_hosts):
        raise ArtifactSecurityError("git_ssh_host_not_allowed")
    if parsed.username or parsed.password:
        raise ArtifactSecurityError("git_url_credentials_rejected")
    host = parsed.hostname
    if not host:
        raise ArtifactSecurityError("git_host_missing")
    if allowed_hosts and host in allowed_hosts:
        return
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ArtifactSecurityError("git_host_resolution_failed") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ArtifactSecurityError("git_ssrf_target_rejected")


def validate_git_commit_sha(commit_sha: str) -> None:
    if len(commit_sha) != 40 or any(char not in "0123456789abcdef" for char in commit_sha):
        raise ArtifactSecurityError("git_commit_sha_required")


def validate_pdf_header(path: str | Path, *, max_bytes: int = 50 * 1024 * 1024) -> None:
    pdf = Path(path)
    if pdf.stat().st_size > max_bytes:
        raise ArtifactSecurityError("pdf_size_exceeded")
    with pdf.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ArtifactSecurityError("pdf_magic_invalid")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
