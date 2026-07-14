from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from backend.app.schemas.teaching_diagram import TeachingDiagramManifest


def atomic_write_manifest(path: Path, manifest: TeachingDiagramManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_copy(update={"generated_at": datetime.now(UTC)})
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def manifest_status(manifest: TeachingDiagramManifest) -> str:
    if not manifest.teaching_diagrams_enabled:
        return "disabled"
    if not manifest.diagrams:
        return "failed" if manifest.errors else "blueprint_only"
    if all(item.display_variant == "ai" for item in manifest.diagrams):
        return "success"
    if any(item.display_variant == "ai" for item in manifest.diagrams):
        return "partial"
    return "blueprint_only"
