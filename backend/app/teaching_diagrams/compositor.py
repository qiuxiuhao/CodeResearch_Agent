from __future__ import annotations

from pathlib import Path
from shutil import copyfile

from backend.app.schemas.teaching_diagram import TeachingDiagramSpec
from backend.app.teaching_diagrams.assets import asset_from_file


class TeachingDiagramCompositor:
    """Deterministic final layer. MVP keeps rule-accurate Blueprint as the overlay source."""

    def compose(
        self,
        *,
        spec: TeachingDiagramSpec,
        blueprint_png: Path,
        ai_dir: Path,
        generated_raw: Path | None = None,
    ) -> dict:
        del spec, generated_raw
        ai_dir.mkdir(parents=True, exist_ok=True)
        styled = ai_dir / "styled_composite.png"
        final = ai_dir / "final.png"
        copyfile(blueprint_png, styled)
        copyfile(styled, final)
        return {
            "styled_composite": asset_from_file(styled, "image/png"),
            "final": asset_from_file(final, "image/png"),
            "warnings": ["compositor_used_blueprint_overlay"],
        }
