from __future__ import annotations

from pathlib import Path


DEFAULT_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_EXTRACT_SIZE_BYTES = 10 * 1024 * 1024


def is_too_large(path: str | Path, max_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES) -> bool:
    return Path(path).stat().st_size > max_bytes


def read_text_safely(path: str | Path, max_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES) -> str:
    file_path = Path(path)
    if file_path.stat().st_size > max_bytes:
        raise ValueError(f"File is too large to read: {file_path}")
    return file_path.read_text(encoding="utf-8")

