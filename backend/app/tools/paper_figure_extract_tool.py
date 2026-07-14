from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.schemas.paper_figure import (
    FigureAsset,
    FigureCaption,
    FigurePreview,
    FigureSelection,
    PaperFigure,
)
from backend.app.vision.config import VisionSettings


CAPTION_PATTERN = re.compile(r"^\s*(figure|fig\.?)\s*([0-9]+(?:\s*[a-z])?)\s*[:.\-]?\s*", re.I)
REFERENCE_PATTERN = re.compile(r"\b(?:figure|fig\.?)\s*([0-9]+(?:\s*[a-z])?)\b", re.I)
IMPORTANT_WORDS = {"architecture", "framework", "overview", "pipeline", "method", "network", "workflow", "model"}


def empty_figure_analysis(*, vision_enabled: bool, consent: bool, status: str = "not_applicable") -> dict:
    return {
        "version": "1.2", "paper_hash": None, "extraction_status": status,
        "vision_status": "disabled" if not vision_enabled else status,
        "vision_vlm_enabled": vision_enabled, "external_vision_consent": consent,
        "limits": {}, "budget": {}, "section_page_map": [], "page_text_index": [],
        "figure_reference_count": {}, "figures": [], "skipped_figures": [],
        "evidence_catalog": [], "warnings": [],
    }


def extract_paper_figures(
    paper_pdf_path: str | Path,
    output_dir: str | Path,
    paper_analysis: dict,
    settings: VisionSettings,
    *,
    external_vision_consent: bool = False,
) -> dict:
    import fitz

    path = Path(paper_pdf_path)
    result = empty_figure_analysis(
        vision_enabled=settings.enabled, consent=external_vision_consent, status="skipped"
    )
    result["limits"] = _limit_snapshot(settings)
    if not path.exists():
        result["extraction_status"] = "failed"
        result["warnings"].append(_warning("paper_figure_pdf_missing", str(path)))
        return result

    paper_hash = _file_sha256(path)
    result["paper_hash"] = paper_hash
    original_dir = Path(output_dir) / "paper_figures" / "original"
    preview_dir = Path(output_dir) / "paper_figures" / "previews"
    original_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    image_object_count = 0
    original_bytes = 0
    candidates: list[dict[str, Any]] = []
    page_texts: dict[int, str] = {}
    timed_out = False

    try:
        with fitz.open(path) as document:
            page_limit = min(document.page_count, settings.paper_max_pages)
            if document.page_count > page_limit:
                result["warnings"].append(_warning("paper_max_pages_exceeded", f"只处理前 {page_limit} 页。"))
            for page_index in range(page_limit):
                if _deadline_exceeded(started, settings):
                    timed_out = True
                    break
                page = document[page_index]
                page_number = page_index + 1
                page_text = page.get_text("text")
                page_texts[page_number] = page_text
                references = [_normalize_label(match.group(1)) for match in REFERENCE_PATTERN.finditer(page_text)]
                result["page_text_index"].append({
                    "page_number": page_number,
                    "text_hash": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                    "text_char_count": len(page_text),
                    "figure_references": references[:100],
                })
                blocks = _text_blocks(page)
                captions = _caption_blocks(blocks)
                image_infos = page.get_image_info(xrefs=True)
                image_object_count += len(image_infos)
                if image_object_count > settings.paper_max_image_objects:
                    allowed = max(0, len(image_infos) - (image_object_count - settings.paper_max_image_objects))
                    image_infos = image_infos[:allowed]
                    result["warnings"].append(_warning("paper_max_image_objects_exceeded", "后续图片对象已跳过。"))
                    image_object_count = settings.paper_max_image_objects
                drawing_rects = _drawing_rects(page, settings, result["warnings"])
                previous_caption_bottom = 0.0
                for caption in captions:
                    if len(candidates) >= settings.paper_max_figure_candidates:
                        result["warnings"].append(_warning("paper_max_figure_candidates_exceeded", "后续 Figure 候选已跳过。"))
                        break
                    if _deadline_exceeded(started, settings):
                        timed_out = True
                        break
                    figure_bbox = _figure_bbox(page.rect, caption["bbox"], image_infos, drawing_rects, previous_caption_bottom)
                    previous_caption_bottom = caption["bbox"][3]
                    normalized_bbox = _normalized_bbox(figure_bbox, page.rect.width, page.rect.height)
                    figure_id = _figure_id(paper_hash, page_number, normalized_bbox, caption["normalized_label"])
                    preview = _render_preview(
                        page, figure_bbox, preview_dir / f"{figure_id}.png", settings, result["warnings"]
                    )
                    assets: list[FigureAsset] = []
                    for info in _images_in_bbox(image_infos, figure_bbox):
                        xref = int(info.get("xref") or 0)
                        if xref <= 0:
                            continue
                        asset, consumed = _extract_original_asset(
                            document, xref, tuple(info.get("bbox", ())), original_dir,
                            settings, original_bytes, result["warnings"],
                        )
                        if asset:
                            assets.append(asset)
                            original_bytes += consumed
                    reference_count = references.count(caption["normalized_label"])
                    section_name = _section_for_page(page_number, paper_analysis.get("sections", []))
                    score, reasons = _selection_score(caption["text"], reference_count, section_name, figure_bbox, page.rect)
                    candidates.append(PaperFigure(
                        figure_id=figure_id,
                        page_number=page_number,
                        page_width=float(page.rect.width),
                        page_height=float(page.rect.height),
                        page_rotation=int(page.rotation or 0) % 360,
                        bbox=figure_bbox,
                        normalized_bbox=normalized_bbox,
                        caption=FigureCaption(**caption),
                        original_assets=assets,
                        canonical_preview=preview,
                        reference_count=reference_count,
                        section_name=section_name,
                        selection=FigureSelection(score=score, reasons=reasons),
                    ).model_dump(mode="json"))
                if timed_out or image_object_count >= settings.paper_max_image_objects:
                    if timed_out:
                        break
    except Exception as exc:
        result["extraction_status"] = "partial" if candidates else "failed"
        result["warnings"].append(_warning("paper_figure_extraction_error", f"{type(exc).__name__}: {exc}"))

    if timed_out:
        result["warnings"].append(_warning("paper_extraction_timeout", "Figure 提取达到时间上限，已保留完成结果。"))
    result["section_page_map"] = _section_page_map(paper_analysis.get("sections", []))
    reference_counts = Counter()
    for text in page_texts.values():
        reference_counts.update(_normalize_label(match.group(1)) for match in REFERENCE_PATTERN.finditer(text))
    result["figure_reference_count"] = dict(sorted(reference_counts.items()))
    candidates = _dedupe_candidates(candidates, result["skipped_figures"])
    candidates.sort(key=lambda item: (
        -float(item["selection"]["score"]), item["page_number"], tuple(item["normalized_bbox"]), item["figure_id"]
    ))
    for index, item in enumerate(candidates):
        selectable = item.get("canonical_preview") is not None
        item["selection"]["selected"] = selectable and index < settings.max_figure_analyses
        if not item["selection"]["selected"]:
            item["selection"]["skip_reason"] = "preview_unavailable" if not selectable else "figure_limit_exceeded"
            result["skipped_figures"].append({
                "figure_id": item["figure_id"], "reason": item["selection"]["skip_reason"]
            })
    result["figures"] = candidates
    if result["extraction_status"] not in {"failed", "partial"}:
        result["extraction_status"] = "success" if candidates else "skipped"
    if not candidates:
        result["warnings"].append(_warning("paper_figure_caption_unavailable", "未检测到可提取的 Figure 图注。"))
    return result


def _text_blocks(page) -> list[dict]:
    blocks = []
    for raw in page.get_text("blocks", sort=True):
        if len(raw) < 5 or not str(raw[4]).strip():
            continue
        blocks.append({"bbox": tuple(float(value) for value in raw[:4]), "text": re.sub(r"\s+", " ", str(raw[4])).strip()})
    return blocks


def _caption_blocks(blocks: list[dict]) -> list[dict]:
    captions = []
    for block in blocks:
        match = CAPTION_PATTERN.match(block["text"])
        if not match:
            continue
        label_number = re.sub(r"\s+", "", match.group(2))
        label = f"Figure {label_number}"
        captions.append({
            "label": label, "normalized_label": _normalize_label(match.group(2)),
            "text": block["text"][:4000], "bbox": block["bbox"], "confidence": "high",
        })
    return captions


def _drawing_rects(page, settings: VisionSettings, warnings: list[dict]) -> list[tuple[float, float, float, float]]:
    if settings.paper_max_drawing_paths_per_page == 0:
        return []
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    if len(drawings) > settings.paper_max_drawing_paths_per_page:
        warnings.append(_warning("paper_max_drawing_paths_exceeded", f"第 {page.number + 1} 页矢量路径过多，已忽略矢量候选。"))
        return []
    rects = []
    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is not None and rect.width > 3 and rect.height > 3:
            rects.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
    return rects


def _figure_bbox(page_rect, caption_bbox, image_infos, drawing_rects, previous_caption_bottom):
    x0, y0, x1, y1 = caption_bbox
    lower_bound = max(0.0, previous_caption_bottom)
    max_lookback = max(lower_bound, y0 - page_rect.height * 0.55)
    related = []
    for info in image_infos:
        bbox = tuple(float(value) for value in info.get("bbox", (0, 0, 0, 0)))
        if len(bbox) == 4 and bbox[1] < y0 and bbox[3] > max_lookback:
            related.append(bbox)
    for bbox in drawing_rects:
        if bbox[1] < y0 and bbox[3] > max_lookback:
            related.append(bbox)
    if related:
        xs0 = [item[0] for item in related] + [x0]
        ys0 = [item[1] for item in related]
        xs1 = [item[2] for item in related] + [x1]
        return _clamp_bbox((min(xs0) - 6, min(ys0) - 6, max(xs1) + 6, y1 + 3), page_rect)
    return _clamp_bbox((page_rect.width * 0.04, max(max_lookback, y0 - page_rect.height * 0.42), page_rect.width * 0.96, y1 + 3), page_rect)


def _render_preview(page, bbox, path: Path, settings: VisionSettings, warnings: list[dict]) -> FigurePreview | None:
    import fitz

    width_pt = max(1.0, bbox[2] - bbox[0])
    height_pt = max(1.0, bbox[3] - bbox[1])
    zoom = settings.render_dpi / 72.0
    pixels = width_pt * zoom * height_pt * zoom
    if pixels > settings.paper_max_render_pixels:
        zoom *= (settings.paper_max_render_pixels / pixels) ** 0.5
    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(bbox), alpha=False)
        if pixmap.width * pixmap.height > settings.paper_max_render_pixels:
            warnings.append(_warning("paper_max_render_pixels_exceeded", "Figure preview 像素数超过上限。"))
            return None
        data = pixmap.tobytes("png")
        path.write_bytes(data)
        return FigurePreview(
            path=str(path), width=pixmap.width, height=pixmap.height, byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(), render_dpi=max(36, round(72 * zoom)),
        )
    except Exception as exc:
        warnings.append(_warning("paper_figure_render_failed", f"{type(exc).__name__}: {exc}"))
        return None


def _extract_original_asset(document, xref, bbox, directory, settings, consumed, warnings):
    try:
        extracted = document.extract_image(xref)
        data = extracted.get("image", b"")
    except Exception:
        return None, 0
    if len(data) > settings.paper_max_single_asset_bytes:
        warnings.append(_warning("paper_max_single_asset_bytes_exceeded", f"xref {xref} 已跳过。"))
        return None, 0
    if consumed + len(data) > settings.paper_max_original_asset_bytes:
        warnings.append(_warning("paper_max_original_asset_bytes_exceeded", "原始图片资产总量达到上限。"))
        return None, 0
    digest = hashlib.sha256(data).hexdigest()
    ext = str(extracted.get("ext") or "bin").lower()
    asset_path = directory / f"xref_{xref}_{digest[:12]}.{ext}"
    if not asset_path.exists():
        asset_path.write_bytes(data)
    mime = f"image/{'jpeg' if ext in {'jpg', 'jpeg'} else ext}"
    return FigureAsset(
        asset_id=f"asset_{digest[:20]}", kind="xref", path=str(asset_path), mime_type=mime,
        byte_size=len(data), sha256=digest, xref=xref, bbox=bbox if len(bbox) == 4 else None,
    ), len(data)


def _images_in_bbox(image_infos, bbox):
    result = []
    for info in image_infos:
        raw = info.get("bbox", ())
        if len(raw) != 4:
            continue
        image_bbox = tuple(float(value) for value in raw)
        if _intersection_area(image_bbox, bbox) > 0:
            result.append(info)
    return result


def _selection_score(caption, reference_count, section_name, bbox, page_rect):
    lowered = caption.lower()
    hits = sorted(word for word in IMPORTANT_WORDS if word in lowered)
    score = len(hits) * 2 + min(reference_count, 5)
    reasons = [f"caption_keyword:{word}" for word in hits]
    if section_name in {"method", "approach", "architecture", "model"}:
        score += 3
        reasons.append(f"section:{section_name}")
    area_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / max(1.0, page_rect.width * page_rect.height)
    if area_ratio >= 0.1:
        score += 1
        reasons.append("substantial_page_area")
    return float(score), reasons


def _dedupe_candidates(candidates, skipped):
    result = []
    by_hash: dict[str, dict] = {}
    for item in candidates:
        preview_hash = (item.get("canonical_preview") or {}).get("sha256")
        key = preview_hash or f"{item['page_number']}:{item['caption']['normalized_label']}:{item['normalized_bbox']}"
        if key in by_hash:
            primary = by_hash[key]
            primary.setdefault("aliases", []).append(item["figure_id"])
            skipped.append({"figure_id": item["figure_id"], "reason": "exact_duplicate", "duplicate_of": primary["figure_id"]})
            continue
        by_hash[key] = item
        result.append(item)
    return result


def _section_page_map(sections):
    return [
        {"name": item.get("name"), "title": item.get("title"), "page_start": item.get("page_start"), "page_end": item.get("page_end")}
        for item in sections if item.get("page_start")
    ]


def _section_for_page(page_number, sections):
    for item in sections:
        start = item.get("page_start")
        end = item.get("page_end") or start
        if start and start <= page_number <= end:
            return item.get("name")
    return None


def _figure_id(paper_hash, page_number, normalized_bbox, normalized_label):
    bbox_part = ",".join(f"{value:.6f}" for value in normalized_bbox)
    identity = f"{paper_hash}|{page_number}|{bbox_part}|{normalized_label}"
    return "fig_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _normalize_label(value):
    return re.sub(r"\s+", "", str(value)).lower().rstrip(".")


def _normalized_bbox(bbox, width, height):
    return tuple(round(max(0.0, min(1.0, value)), 6) for value in (
        bbox[0] / width, bbox[1] / height, bbox[2] / width, bbox[3] / height,
    ))


def _clamp_bbox(bbox, page_rect):
    x0 = max(0.0, min(float(page_rect.width), float(bbox[0])))
    y0 = max(0.0, min(float(page_rect.height), float(bbox[1])))
    x1 = max(x0 + 1.0, min(float(page_rect.width), float(bbox[2])))
    y1 = max(y0 + 1.0, min(float(page_rect.height), float(bbox[3])))
    return (x0, y0, x1, y1)


def _intersection_area(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _deadline_exceeded(started, settings):
    return time.monotonic() - started >= settings.paper_extraction_timeout_seconds


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _limit_snapshot(settings):
    return {
        "max_pages": settings.paper_max_pages,
        "max_image_objects": settings.paper_max_image_objects,
        "max_figure_candidates": settings.paper_max_figure_candidates,
        "max_original_asset_bytes": settings.paper_max_original_asset_bytes,
        "max_single_asset_bytes": settings.paper_max_single_asset_bytes,
        "max_render_pixels": settings.paper_max_render_pixels,
        "max_drawing_paths_per_page": settings.paper_max_drawing_paths_per_page,
        "extraction_timeout_seconds": settings.paper_extraction_timeout_seconds,
    }


def _warning(code, message):
    return {"code": code, "message": message, "recoverable": True}
