from __future__ import annotations

from pathlib import Path

import fitz


ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}


def validate_image_file(
    path: Path,
    *,
    expected_mime: str | None = None,
    max_bytes: int,
    max_width: int,
    max_height: int,
) -> dict:
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise ValueError("image byte limit exceeded")
    mime = _detect_mime(data)
    if mime not in ALLOWED_IMAGE_MIME:
        raise ValueError("unsupported image mime")
    if expected_mime and expected_mime in ALLOWED_IMAGE_MIME and mime != expected_mime:
        raise ValueError("image mime mismatch")
    pixmap = fitz.Pixmap(str(path))
    if pixmap.width > max_width or pixmap.height > max_height:
        raise ValueError("image dimensions exceed configured limit")
    return {"mime_type": mime, "width": pixmap.width, "height": pixmap.height, "byte_size": len(data)}


def write_validated_image(
    path: Path,
    image_bytes: bytes,
    *,
    mime_type: str,
    max_bytes: int,
    max_width: int,
    max_height: int,
) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    try:
        return validate_image_file(
            path,
            expected_mime=mime_type,
            max_bytes=max_bytes,
            max_width=max_width,
            max_height=max_height,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _detect_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.lstrip().startswith((b"<svg", b"<html", b"<!DOCTYPE")):
        raise ValueError("active or vector content is not allowed as generated image")
    return "application/octet-stream"
