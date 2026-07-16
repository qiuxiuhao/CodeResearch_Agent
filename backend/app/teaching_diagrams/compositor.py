from __future__ import annotations

from pathlib import Path

import fitz

from backend.app.image_generation.safety import validate_image_file
from backend.app.schemas.teaching_diagram import TeachingDiagramSpec
from backend.app.teaching_diagrams.assets import asset_from_file
from backend.app.teaching_diagrams.blueprint_renderer import (
    HEIGHT,
    WIDTH,
    draw_deterministic_overlay,
    layout_modules,
    resolve_font,
)


class TeachingDiagramCompositor:
    """Compose vendor pixels with deterministic rule-backed diagram overlays."""

    def compose(
        self,
        *,
        spec: TeachingDiagramSpec,
        blueprint_png: Path,
        ai_dir: Path,
        generated_raw: Path | None = None,
        task_root: Path | None = None,
        max_bytes: int = 10_485_760,
        max_width: int = 1536,
        max_height: int = 1536,
    ) -> dict:
        del blueprint_png
        ai_dir.mkdir(parents=True, exist_ok=True)
        if generated_raw is None or not generated_raw.is_file():
            return {
                "styled_composite": None,
                "warnings": ["styled_composite_skipped_no_generated_raw"],
            }
        validate_image_file(
            generated_raw,
            expected_mime="image/png",
            max_bytes=max_bytes,
            max_width=max_width,
            max_height=max_height,
        )
        styled = ai_dir / "styled_composite.png"
        document = fitz.open()
        try:
            page = document.new_page(width=WIDTH, height=HEIGHT)
            page.insert_image(fitz.Rect(0, 0, WIDTH, HEIGHT), filename=str(generated_raw), keep_proportion=False)
            draw_deterministic_overlay(page, spec, layout_modules(spec), resolve_font(spec), draw_background=False)
            pixmap = page.get_pixmap(alpha=False)
            pixmap.save(str(styled))
        finally:
            document.close()
        validate_image_file(
            styled,
            expected_mime="image/png",
            max_bytes=max_bytes,
            max_width=max_width,
            max_height=max_height,
        )
        return {
            "styled_composite": asset_from_file(styled, "image/png", relative_to=task_root),
            "warnings": ["compositor_used_ai_background_and_deterministic_overlay"],
        }
