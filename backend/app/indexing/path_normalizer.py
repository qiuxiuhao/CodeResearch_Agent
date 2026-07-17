from __future__ import annotations

import re
import unicodedata


WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_index_path(value: str) -> str:
    """Return a safe, repository-relative, case-preserving POSIX path."""
    raw = unicodedata.normalize("NFC", value.strip()).replace("\\", "/")
    if not raw:
        raise ValueError("Index path must not be empty.")
    if raw.startswith("/") or raw.startswith("//") or WINDOWS_DRIVE.match(raw):
        raise ValueError("Index path must be repository-relative.")

    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("Index path must not escape the repository.")
        normalized = unicodedata.normalize("NFC", part)
        if not normalized:
            continue
        parts.append(normalized)
    if not parts:
        raise ValueError("Index path must contain a file or directory name.")
    return "/".join(parts)


def normalize_structured_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)
