from __future__ import annotations

import html
import math
import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import fitz

from backend.app.schemas.teaching_diagram import TeachingDiagramSpec
from backend.app.teaching_diagrams.assets import asset_from_file


WIDTH = 1280
HEIGHT = 720
MARGIN = 52
CARD_W = 220
CARD_H = 88
MODULE_TOP = 170
MODULE_BOTTOM = 475


@dataclass(frozen=True)
class FontChoice:
    family: str
    fontfile: str | None
    warning: str | None = None


class BlueprintRenderer:
    def render(self, spec: TeachingDiagramSpec, output_dir: Path, *, task_root: Path | None = None) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        layout = layout_modules(spec)
        font = resolve_font(spec)
        svg_path = output_dir / "blueprint_svg" / f"{spec.diagram_id}.svg"
        png_path = output_dir / "blueprint_png" / f"{spec.diagram_id}.png"
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(render_svg(spec, layout, font), encoding="utf-8")
        render_png(spec, layout, png_path, font)
        warnings = []
        if font.warning:
            warnings.append(font.warning)
        return {
            "svg": asset_from_file(svg_path, "image/svg+xml", relative_to=task_root),
            "png": asset_from_file(png_path, "image/png", relative_to=task_root),
            "warnings": warnings,
        }


def layout_modules(spec: TeachingDiagramSpec) -> dict[str, tuple[int, int]]:
    count = len(spec.modules)
    if count == 0:
        return {}
    columns = min(4, max(1, math.ceil(math.sqrt(count * 1.35))))
    rows = math.ceil(count / columns)
    available_w = WIDTH - MARGIN * 2
    available_h = MODULE_BOTTOM - MODULE_TOP
    x_gap = 0 if columns == 1 else max(28, (available_w - columns * CARD_W) // (columns - 1))
    y_gap = 0 if rows == 1 else max(24, (available_h - rows * CARD_H) // (rows - 1))
    layout: dict[str, tuple[int, int]] = {}
    for index, module in enumerate(spec.modules):
        row, col = divmod(index, columns)
        x = MARGIN + col * (CARD_W + x_gap)
        y = MODULE_TOP + row * (CARD_H + y_gap)
        layout[module.id] = (int(x), int(y))
    return layout


def resolve_font(spec: TeachingDiagramSpec | None = None) -> FontChoice:
    configured_path = os.getenv("TEACHING_DIAGRAM_FONT_PATH", "").strip()
    configured_name = os.getenv("TEACHING_DIAGRAM_FONT_NAME", "").strip()
    if configured_path and Path(configured_path).is_file():
        return FontChoice(configured_name or Path(configured_path).stem, configured_path)
    for candidate in _candidate_font_paths():
        if candidate.is_file():
            return FontChoice(configured_name or candidate.stem, str(candidate))
    if configured_name:
        return FontChoice(configured_name, None)
    warning = None
    if spec and _contains_cjk(_spec_text(spec)):
        warning = "teaching_diagram_font_unavailable"
    return FontChoice("Arial, Helvetica, sans-serif", None, warning)


def render_svg(spec: TeachingDiagramSpec, layout: dict[str, tuple[int, int]], font: FontChoice) -> str:
    family = _esc(font.family)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        "<defs>",
        '<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">',
        '<path d="M0,0 L0,6 L9,3 z" fill="#334155"/></marker>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{MARGIN}" y="52" font-size="27" font-family="{family}" fill="#0f172a">{_esc(_clip(spec.source_entity.title, 48))}</text>',
        f'<text x="{MARGIN}" y="86" font-size="16" font-family="{family}" fill="#475569">{_esc(_clip(spec.one_sentence_summary, 92))}</text>',
    ]
    _append_sections_svg(parts, spec, family)
    for connection in spec.connections:
        if connection.source_module_id not in layout or connection.target_module_id not in layout:
            continue
        parts.append(_svg_arrow(layout[connection.source_module_id], layout[connection.target_module_id], connection.label or "", family))
    for module in spec.modules:
        x, y = layout[module.id]
        fill = _fill(module.kind)
        parts.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="8" fill="{fill}" stroke="#334155" stroke-width="1.5"/>')
        for line_index, line in enumerate(_wrap(module.label, 18)[:3]):
            parts.append(f'<text x="{x + 14}" y="{y + 28 + line_index * 18}" font-size="15" font-family="{family}" fill="#0f172a">{_esc(line)}</text>')
        shape = next((item for item in spec.shapes if item.module_id == module.id), None)
        if shape:
            parts.append(f'<text x="{x + 14}" y="{y + 76}" font-size="12" font-family="{family}" fill="#475569">{_esc(_clip(shape.label, 28))}</text>')
    _append_text_block_svg(parts, "教学步骤", spec.steps, 70, 515, family, 5)
    _append_text_block_svg(parts, "公式", [item.text for item in spec.formulas], 500, 515, family, 3)
    _append_text_block_svg(parts, "学习提示", spec.learning_tips, 500, 625, family, 2)
    _append_legend_svg(parts, spec, family)
    parts.append("</svg>")
    return "\n".join(parts)


def render_png(spec: TeachingDiagramSpec, layout: dict[str, tuple[int, int]], path: Path, font: FontChoice) -> None:
    document = fitz.open()
    page = document.new_page(width=WIDTH, height=HEIGHT)
    draw_deterministic_overlay(page, spec, layout, font, draw_background=True)
    pixmap = page.get_pixmap(alpha=False)
    pixmap.save(str(path))
    document.close()


def draw_deterministic_overlay(
    page,
    spec: TeachingDiagramSpec,
    layout: dict[str, tuple[int, int]],
    font: FontChoice,
    *,
    draw_background: bool = False,
) -> None:
    if draw_background:
        page.draw_rect(fitz.Rect(0, 0, WIDTH, HEIGHT), fill=(0.972, 0.98, 0.988), color=None)
    else:
        page.draw_rect(fitz.Rect(34, 24, WIDTH - 34, HEIGHT - 24), fill=(1, 1, 1), color=(0.82, 0.86, 0.91), fill_opacity=0.88, width=0.6)
    _insert_text(page, fitz.Rect(MARGIN, 26, WIDTH - MARGIN, 64), _clip(spec.source_entity.title, 54), 23, (0.06, 0.09, 0.16), font)
    _insert_text(page, fitz.Rect(MARGIN, 70, WIDTH - MARGIN, 105), _clip(spec.one_sentence_summary, 110), 12, (0.28, 0.33, 0.41), font)
    _insert_text(page, fitz.Rect(MARGIN, 112, 760, 148), " / ".join(_clip(item.title, 20) for item in spec.sections[:3]), 10, (0.39, 0.45, 0.55), font)
    for connection in spec.connections:
        if connection.source_module_id not in layout or connection.target_module_id not in layout:
            continue
        _draw_arrow(page, layout[connection.source_module_id], layout[connection.target_module_id])
    for module in spec.modules:
        x, y = layout[module.id]
        fill = _fill_rgb(module.kind)
        page.draw_rect(fitz.Rect(x, y, x + CARD_W, y + CARD_H), fill=fill, color=(0.20, 0.25, 0.33), width=1)
        _insert_text(page, fitz.Rect(x + 12, y + 12, x + CARD_W - 12, y + 64), "\n".join(_wrap(module.label, 17)[:3]), 11, (0.06, 0.09, 0.16), font)
        shape = next((item for item in spec.shapes if item.module_id == module.id), None)
        if shape:
            _insert_text(page, fitz.Rect(x + 12, y + 66, x + CARD_W - 12, y + 86), _clip(shape.label, 28), 8, (0.28, 0.33, 0.41), font)
    _insert_text(page, fitz.Rect(70, 498, 440, 676), "教学步骤\n" + "\n".join(_clip(item, 44) for item in spec.steps[:5]), 10, (0.20, 0.25, 0.33), font)
    formula_lines = [item.text for item in spec.formulas[:3]] or ["无已确认公式"]
    _insert_text(page, fitz.Rect(500, 498, 780, 595), "公式\n" + "\n".join(_clip(item, 36) for item in formula_lines), 10, (0.20, 0.25, 0.33), font)
    _insert_text(page, fitz.Rect(500, 610, 780, 676), "学习提示\n" + "\n".join(_clip(item, 34) for item in spec.learning_tips[:2]), 10, (0.20, 0.25, 0.33), font)
    _insert_text(page, fitz.Rect(850, 498, 1180, 676), "图例\n" + "\n".join(f"{item.label}: {_clip(item.meaning, 24)}" for item in spec.legend[:4]), 10, (0.20, 0.25, 0.33), font)


def _insert_text(page, rect, text, size, color, font: FontChoice):
    kwargs = {"fontsize": size, "color": color, "align": 0}
    if font.fontfile:
        kwargs["fontfile"] = font.fontfile
        kwargs["fontname"] = "td_cjk"
    else:
        kwargs["fontname"] = "helv"
    page.insert_textbox(rect, text, **kwargs)


def _draw_arrow(page, start_xy: tuple[int, int], end_xy: tuple[int, int]) -> None:
    points = _route_points(start_xy, end_xy)
    for first, second in zip(points, points[1:]):
        page.draw_line(fitz.Point(*first), fitz.Point(*second), color=(0.20, 0.25, 0.33), width=1.4)
    end, left, right = _arrowhead_points(points[-2], points[-1])
    page.draw_line(fitz.Point(*end), fitz.Point(*left), color=(0.20, 0.25, 0.33), width=1.4)
    page.draw_line(fitz.Point(*end), fitz.Point(*right), color=(0.20, 0.25, 0.33), width=1.4)


def _route_points(start_xy: tuple[int, int], end_xy: tuple[int, int]) -> list[tuple[int, int]]:
    x1, y1 = start_xy
    x2, y2 = end_xy
    cx1, cy1 = x1 + CARD_W // 2, y1 + CARD_H // 2
    cx2, cy2 = x2 + CARD_W // 2, y2 + CARD_H // 2
    dx, dy = cx2 - cx1, cy2 - cy1
    if abs(dx) >= abs(dy):
        if dx >= 0:
            start = (x1 + CARD_W, cy1)
            end = (x2, cy2)
        else:
            start = (x1, cy1)
            end = (x2 + CARD_W, cy2)
    elif dy >= 0:
        start = (cx1, y1 + CARD_H)
        end = (cx2, y2)
    else:
        start = (cx1, y1)
        end = (cx2, y2 + CARD_H)
    if start[0] == end[0] or start[1] == end[1]:
        return [start, end]
    if abs(dx) >= abs(dy):
        mid_x = (start[0] + end[0]) // 2
        return [start, (mid_x, start[1]), (mid_x, end[1]), end]
    mid_y = (start[1] + end[1]) // 2
    return [start, (start[0], mid_y), (end[0], mid_y), end]


def _arrowhead_points(previous: tuple[int, int], end: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    vx = end[0] - previous[0]
    vy = end[1] - previous[1]
    length = math.hypot(vx, vy) or 1.0
    ux, uy = vx / length, vy / length
    px, py = -uy, ux
    size = 11
    spread = 6
    left = (round(end[0] - ux * size + px * spread), round(end[1] - uy * size + py * spread))
    right = (round(end[0] - ux * size - px * spread), round(end[1] - uy * size - py * spread))
    return end, left, right


def _svg_arrow(start_xy: tuple[int, int], end_xy: tuple[int, int], label: str, family: str) -> str:
    points = _route_points(start_xy, end_xy)
    attr = " ".join(f"{x},{y}" for x, y in points)
    mid_x, mid_y = points[len(points) // 2]
    return (
        f'<polyline points="{attr}" fill="none" stroke="#334155" stroke-width="2" marker-end="url(#arrow)"/>'
        f'<text x="{mid_x + 4}" y="{mid_y - 8}" font-size="12" font-family="{family}" fill="#475569">{_esc(_clip(label, 18))}</text>'
    )


def _append_sections_svg(parts: list[str], spec: TeachingDiagramSpec, family: str) -> None:
    for index, section in enumerate(spec.sections[:3]):
        parts.append(f'<text x="{MARGIN + index * 230}" y="132" font-size="13" font-family="{family}" fill="#64748b">{_esc(_clip(section.title, 22))}</text>')


def _append_text_block_svg(parts: list[str], title: str, lines: list[str], x: int, y: int, family: str, max_lines: int) -> None:
    parts.append(f'<text x="{x}" y="{y}" font-size="17" font-family="{family}" fill="#0f172a">{_esc(title)}</text>')
    for index, line in enumerate(lines[:max_lines], start=1):
        parts.append(f'<text x="{x}" y="{y + 24 + index * 20}" font-size="13" font-family="{family}" fill="#334155">{_esc(_clip(line, 54))}</text>')


def _append_legend_svg(parts: list[str], spec: TeachingDiagramSpec, family: str) -> None:
    x, y = 850, 515
    parts.append(f'<text x="{x}" y="{y}" font-size="17" font-family="{family}" fill="#0f172a">图例</text>')
    for index, item in enumerate(spec.legend[:4]):
        yy = y + 30 + index * 30
        parts.append(f'<rect x="{x}" y="{yy - 14}" width="18" height="18" fill="{_esc(item.color)}" stroke="#334155"/>')
        parts.append(f'<text x="{x + 30}" y="{yy}" font-size="13" font-family="{family}" fill="#334155">{_esc(item.label)}：{_esc(_clip(item.meaning, 28))}</text>')


def _candidate_font_paths() -> list[Path]:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    if shutil.which("fc-match"):
        try:
            output = subprocess.run(
                ["fc-match", "-f", "%{file}", "Noto Sans CJK SC"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if output.stdout.strip():
                candidates.insert(0, output.stdout.strip())
        except Exception:
            pass
    return [Path(item) for item in candidates]


def _fill(kind: str) -> str:
    return {"input": "#dbeafe", "output": "#fef3c7", "layer": "#dcfce7", "operation": "#ede9fe", "function": "#e0f2fe"}.get(kind, "#e2e8f0")


def _fill_rgb(kind: str) -> tuple[float, float, float]:
    return {
        "input": (0.86, 0.92, 0.99),
        "output": (0.99, 0.95, 0.78),
        "layer": (0.86, 0.99, 0.91),
        "operation": (0.93, 0.91, 0.99),
        "function": (0.88, 0.97, 1.0),
    }.get(kind, (0.89, 0.92, 0.95))


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=True) or [text[:width]]


def _clip(text: str, length: int) -> str:
    return text if len(text) <= length else text[: max(0, length - 1)] + "..."


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _spec_text(spec: TeachingDiagramSpec) -> str:
    return "\n".join(
        [
            spec.source_entity.title,
            spec.one_sentence_summary,
            *[item.label for item in spec.modules],
            *spec.steps,
            *spec.learning_tips,
        ]
    )
