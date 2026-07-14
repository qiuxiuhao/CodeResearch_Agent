from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from backend.app.schemas.teaching_diagram import TeachingDiagramAsset


def asset_from_file(path: Path, mime_type: str) -> TeachingDiagramAsset:
    data = path.read_bytes()
    width, height = _image_size(path, mime_type)
    return TeachingDiagramAsset(
        path=str(path),
        mime_type=mime_type,
        width=width,
        height=height,
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _image_size(path: Path, mime_type: str) -> tuple[int, int]:
    if mime_type == "image/svg+xml":
        text = path.read_text(encoding="utf-8", errors="ignore")
        import re

        match = re.search(r"<svg[^>]+width=\"(\d+)\"[^>]+height=\"(\d+)\"", text)
        if match:
            return int(match.group(1)), int(match.group(2))
        return 1280, 720
    pixmap = fitz.Pixmap(str(path))
    return pixmap.width, pixmap.height
