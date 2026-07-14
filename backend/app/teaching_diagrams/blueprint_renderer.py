from __future__ import annotations

import html
import textwrap
from pathlib import Path

import fitz

from backend.app.schemas.teaching_diagram import TeachingDiagramSpec
from backend.app.teaching_diagrams.assets import asset_from_file


WIDTH = 1280
HEIGHT = 720
MARGIN = 52
CARD_W = 210
CARD_H = 92


class BlueprintRenderer:
    def render(self, spec: TeachingDiagramSpec, output_dir: Path) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        layout = _layout_modules(spec)
        svg_path = output_dir / "blueprint_svg" / f"{spec.diagram_id}.svg"
        png_path = output_dir / "blueprint_png" / f"{spec.diagram_id}.png"
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(_render_svg(spec, layout), encoding="utf-8")
        _render_png(spec, layout, png_path)
        warnings = []
        if _contains_cjk(spec.one_sentence_summary + "".join(item.label for item in spec.modules)):
            warnings.append("blueprint_font_fallback: 使用内置字体绘制 PNG，系统缺少中文字体时可能影响本地预览。")
        return {
            "svg": asset_from_file(svg_path, "image/svg+xml"),
            "png": asset_from_file(png_path, "image/png"),
            "warnings": warnings,
        }


def _layout_modules(spec: TeachingDiagramSpec) -> dict[str, tuple[int, int]]:
    count = max(1, len(spec.modules))
    available_w = WIDTH - MARGIN * 2 - CARD_W
    step = max(170, available_w // max(1, count - 1)) if count > 1 else 0
    y = 265
    return {
        module.id: (MARGIN + min(index * step, available_w), y + (index % 2) * 34)
        for index, module in enumerate(spec.modules)
    }


def _render_svg(spec: TeachingDiagramSpec, layout: dict[str, tuple[int, int]]) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{MARGIN}" y="56" font-size="28" font-family="Arial, sans-serif" fill="#0f172a">{_esc(spec.source_entity.title)}</text>',
        f'<text x="{MARGIN}" y="92" font-size="18" font-family="Arial, sans-serif" fill="#475569">{_esc(_clip(spec.one_sentence_summary, 90))}</text>',
    ]
    for connection in spec.connections:
        if connection.source_module_id not in layout or connection.target_module_id not in layout:
            continue
        x1, y1 = layout[connection.source_module_id]
        x2, y2 = layout[connection.target_module_id]
        parts.append(_svg_arrow(x1 + CARD_W, y1 + CARD_H // 2, x2, y2 + CARD_H // 2, connection.label or ""))
    for module in spec.modules:
        x, y = layout[module.id]
        fill = {"input": "#dbeafe", "output": "#fef3c7", "layer": "#dcfce7", "operation": "#ede9fe"}.get(module.kind, "#e2e8f0")
        parts.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="8" fill="{fill}" stroke="#334155" stroke-width="1.5"/>')
        for line_index, line in enumerate(_wrap(module.label, 17)[:3]):
            parts.append(f'<text x="{x + 14}" y="{y + 30 + line_index * 20}" font-size="16" font-family="Arial, sans-serif" fill="#0f172a">{_esc(line)}</text>')
        shape = next((item for item in spec.shapes if item.module_id == module.id), None)
        if shape:
            parts.append(f'<text x="{x + 14}" y="{y + 80}" font-size="12" font-family="Arial, sans-serif" fill="#475569">{_esc(_clip(shape.label, 24))}</text>')
    _append_text_block(parts, "教学步骤", spec.steps, 70, 500)
    _append_legend(parts, spec)
    parts.append("</svg>")
    return "\n".join(parts)


def _render_png(spec: TeachingDiagramSpec, layout: dict[str, tuple[int, int]], path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=WIDTH, height=HEIGHT)
    page.draw_rect(fitz.Rect(0, 0, WIDTH, HEIGHT), fill=(0.972, 0.98, 0.988), color=None)
    _insert_text(page, fitz.Rect(MARGIN, 28, WIDTH - MARGIN, 70), spec.source_entity.title, 24, (0.06, 0.09, 0.16))
    _insert_text(page, fitz.Rect(MARGIN, 74, WIDTH - MARGIN, 112), _clip(spec.one_sentence_summary, 110), 13, (0.28, 0.33, 0.41))
    for connection in spec.connections:
        if connection.source_module_id not in layout or connection.target_module_id not in layout:
            continue
        x1, y1 = layout[connection.source_module_id]
        x2, y2 = layout[connection.target_module_id]
        start = fitz.Point(x1 + CARD_W, y1 + CARD_H // 2)
        end = fitz.Point(x2, y2 + CARD_H // 2)
        page.draw_line(start, end, color=(0.20, 0.25, 0.33), width=1.5)
        page.draw_line(end, fitz.Point(end.x - 10, end.y - 6), color=(0.20, 0.25, 0.33), width=1.5)
        page.draw_line(end, fitz.Point(end.x - 10, end.y + 6), color=(0.20, 0.25, 0.33), width=1.5)
    for module in spec.modules:
        x, y = layout[module.id]
        fill = {"input": (0.86, 0.92, 0.99), "output": (0.99, 0.95, 0.78), "layer": (0.86, 0.99, 0.91), "operation": (0.93, 0.91, 0.99)}.get(module.kind, (0.89, 0.92, 0.95))
        page.draw_rect(fitz.Rect(x, y, x + CARD_W, y + CARD_H), fill=fill, color=(0.20, 0.25, 0.33), width=1)
        _insert_text(page, fitz.Rect(x + 12, y + 14, x + CARD_W - 12, y + 66), "\n".join(_wrap(module.label, 16)[:3]), 12, (0.06, 0.09, 0.16))
        shape = next((item for item in spec.shapes if item.module_id == module.id), None)
        if shape:
            _insert_text(page, fitz.Rect(x + 12, y + 68, x + CARD_W - 12, y + 88), _clip(shape.label, 28), 8, (0.28, 0.33, 0.41))
    _insert_text(page, fitz.Rect(70, 486, 600, 520), "教学步骤", 16, (0.06, 0.09, 0.16))
    _insert_text(page, fitz.Rect(70, 520, 760, 680), "\n".join(spec.steps[:6]), 11, (0.20, 0.25, 0.33))
    _insert_text(page, fitz.Rect(860, 500, 1180, 680), "图例\n" + "\n".join(f"{item.label}: {item.meaning}" for item in spec.legend[:4]), 11, (0.20, 0.25, 0.33))
    pixmap = page.get_pixmap(alpha=False)
    pixmap.save(str(path))
    document.close()


def _insert_text(page, rect, text, size, color):
    page.insert_textbox(rect, text, fontsize=size, fontname="helv", color=color, align=0)


def _svg_arrow(x1: int, y1: int, x2: int, y2: int, label: str) -> str:
    mid_x = (x1 + x2) // 2
    mid_y = (y1 + y2) // 2 - 8
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#334155" stroke-width="2" marker-end="url(#arrow)"/>'
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L9,3 z" fill="#334155"/></marker></defs>'
        f'<text x="{mid_x}" y="{mid_y}" font-size="12" font-family="Arial, sans-serif" fill="#475569">{_esc(_clip(label, 18))}</text>'
    )


def _append_text_block(parts: list[str], title: str, lines: list[str], x: int, y: int) -> None:
    parts.append(f'<text x="{x}" y="{y}" font-size="20" font-family="Arial, sans-serif" fill="#0f172a">{_esc(title)}</text>')
    for index, line in enumerate(lines[:6], start=1):
        parts.append(f'<text x="{x}" y="{y + 28 + index * 22}" font-size="15" font-family="Arial, sans-serif" fill="#334155">{_esc(_clip(line, 70))}</text>')


def _append_legend(parts: list[str], spec: TeachingDiagramSpec) -> None:
    x, y = 860, 500
    parts.append(f'<text x="{x}" y="{y}" font-size="20" font-family="Arial, sans-serif" fill="#0f172a">图例</text>')
    for index, item in enumerate(spec.legend[:4]):
        yy = y + 34 + index * 34
        parts.append(f'<rect x="{x}" y="{yy - 15}" width="20" height="20" fill="{_esc(item.color)}" stroke="#334155"/>')
        parts.append(f'<text x="{x + 32}" y="{yy}" font-size="14" font-family="Arial, sans-serif" fill="#334155">{_esc(item.label)}：{_esc(_clip(item.meaning, 28))}</text>')


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=True) or [text[:width]]


def _clip(text: str, length: int) -> str:
    return text if len(text) <= length else text[: max(0, length - 1)] + "…"


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)
