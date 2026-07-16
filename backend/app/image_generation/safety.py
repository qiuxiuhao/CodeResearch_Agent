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
    try:
        width, height = pixmap.width, pixmap.height
    finally:
        pixmap = None  # type: ignore[assignment]
    if width > max_width or height > max_height:
        raise ValueError("image dimensions exceed configured limit")
    if width * height > max_width * max_height:
        raise ValueError("image pixel count exceeds configured limit")
    return {"mime_type": mime, "width": width, "height": height, "byte_size": len(data)}


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
    input_mime = _detect_mime(image_bytes)
    if mime_type in ALLOWED_IMAGE_MIME and input_mime != mime_type:
        raise ValueError("image mime mismatch")
    png_bytes = _normalize_to_png(image_bytes, max_width=max_width, max_height=max_height)
    if len(png_bytes) > max_bytes:
        raise ValueError("image byte limit exceeded")
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    path.write_bytes(png_bytes)
    try:
        return validate_image_file(
            path,
            expected_mime="image/png",
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


def _normalize_to_png(image_bytes: bytes, *, max_width: int, max_height: int) -> bytes:
    mime = _detect_mime(image_bytes)
    if mime not in ALLOWED_IMAGE_MIME:
        raise ValueError("unsupported image mime")
    doc = fitz.open(stream=image_bytes, filetype=_filetype_for_mime(mime))
    try:
        if doc.page_count < 1:
            raise ValueError("image decode failed")
        page = doc[0]
        pixmap = page.get_pixmap(alpha=False)
        if pixmap.width > max_width or pixmap.height > max_height:
            raise ValueError("image dimensions exceed configured limit")
        if pixmap.width * pixmap.height > max_width * max_height:
            raise ValueError("image pixel count exceeds configured limit")
        try:
            return pixmap.tobytes("png")
        finally:
            pixmap = None  # type: ignore[assignment]
    finally:
        doc.close()


def _filetype_for_mime(mime: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}[mime]
