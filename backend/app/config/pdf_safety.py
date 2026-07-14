from __future__ import annotations

import os

from pydantic import BaseModel, Field


class PDFSafetySettings(BaseModel):
    max_file_bytes: int = Field(default=52_428_800, ge=1024)
    max_pages: int = Field(default=100, ge=1, le=5000)
    max_text_chars: int = Field(default=2_000_000, ge=1)
    parse_timeout_seconds: float = Field(default=60, ge=0.01, le=3600)

    @classmethod
    def from_env(cls) -> "PDFSafetySettings":
        return cls(
            max_file_bytes=_int_env("PAPER_MAX_FILE_BYTES", 52_428_800),
            max_pages=_int_env("PAPER_MAX_PAGES", 100),
            max_text_chars=_int_env("PAPER_MAX_TEXT_CHARS", 2_000_000),
            parse_timeout_seconds=_float_env("PAPER_PARSE_TIMEOUT_SECONDS", 60),
        )


def zip_max_file_bytes() -> int:
    value = _int_env("ZIP_MAX_FILE_BYTES", 104_857_600)
    if value < 1024:
        raise ValueError("ZIP_MAX_FILE_BYTES must be at least 1024.")
    return value


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default

