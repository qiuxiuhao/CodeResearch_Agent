from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

from backend.app.schemas.repo import UnzipResult
from backend.app.utils.file_utils import DEFAULT_MAX_EXTRACT_SIZE_BYTES
from backend.app.utils.path_utils import (
    DANGEROUS_EXTENSIONS,
    is_within_directory,
    resolve_path,
)


def unzip_project(
    zip_path: str | Path,
    output_root: str | Path = "outputs",
    task_id: str | None = None,
    max_member_size: int = DEFAULT_MAX_EXTRACT_SIZE_BYTES,
) -> UnzipResult:
    source_zip = resolve_path(zip_path)
    current_task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
    output_dir = resolve_path(output_root) / current_task_id
    repo_path = output_dir / "source"
    skipped_files: list[dict] = []
    errors: list[dict] = []

    if not source_zip.exists():
        errors.append(_error("unzip_tool", str(source_zip), "FileNotFoundError", "ZIP file does not exist."))
        return UnzipResult(
            success=False,
            task_id=current_task_id,
            zip_path=str(source_zip),
            output_dir=str(output_dir),
            repo_path=None,
            errors=errors,
        )

    if not zipfile.is_zipfile(source_zip):
        errors.append(_error("unzip_tool", str(source_zip), "BadZipFile", "Input path is not a valid ZIP file."))
        return UnzipResult(
            success=False,
            task_id=current_task_id,
            zip_path=str(source_zip),
            output_dir=str(output_dir),
            repo_path=None,
            errors=errors,
        )

    repo_path.mkdir(parents=True, exist_ok=True)
    extracted_count = 0

    try:
        with zipfile.ZipFile(source_zip) as archive:
            for member in archive.infolist():
                member_name = member.filename
                reason = _skip_reason(member_name, member.file_size, max_member_size)
                target = repo_path / member_name
                if reason is None and not is_within_directory(repo_path, target):
                    reason = "path_traversal"
                if reason:
                    skipped_files.append({"path": member_name, "reason": reason})
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    destination.write(source.read())
                extracted_count += 1
    except zipfile.BadZipFile as exc:
        errors.append(_error("unzip_tool", str(source_zip), type(exc).__name__, str(exc)))
        return UnzipResult(
            success=False,
            task_id=current_task_id,
            zip_path=str(source_zip),
            output_dir=str(output_dir),
            repo_path=str(repo_path),
            extracted_file_count=extracted_count,
            skipped_files=skipped_files,
            errors=errors,
        )

    return UnzipResult(
        success=len(errors) == 0,
        task_id=current_task_id,
        zip_path=str(source_zip),
        output_dir=str(output_dir),
        repo_path=str(repo_path),
        extracted_file_count=extracted_count,
        skipped_files=skipped_files,
        errors=errors,
    )


def _skip_reason(member_name: str, file_size: int, max_member_size: int) -> str | None:
    path = Path(member_name)
    if Path(member_name).is_absolute():
        return "absolute_path"
    if ".." in path.parts:
        return "path_traversal"
    if path.suffix.lower() in DANGEROUS_EXTENSIONS:
        return "dangerous_extension"
    if file_size > max_member_size:
        return "file_too_large"
    return None


def _error(tool: str, path: str, error_type: str, message: str) -> dict:
    return {
        "tool": tool,
        "path": path,
        "error_type": error_type,
        "message": message,
    }

