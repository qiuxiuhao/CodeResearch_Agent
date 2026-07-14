from pathlib import Path

from backend.app.tools.paper_figure_extract_tool import (
    REFERENCE_PATTERN,
    _caption_blocks,
    _figure_bbox,
    extract_paper_figures,
)
from backend.app.vision.config import VisionSettings


def _write_figure_pdf(path: Path, pages: int = 1) -> None:
    import fitz

    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=600, height=800)
        page.insert_text((50, 50), "Method")
        page.draw_rect(fitz.Rect(90, 130, 510, 330), color=(0, 0, 0), width=2)
        page.insert_text((130, 200), "Input")
        page.insert_text((280, 200), "Encoder")
        page.insert_text((430, 200), "Output")
        page.insert_textbox(
            fitz.Rect(70, 350, 530, 410),
            f"Figure {index + 1}. Overview architecture and workflow of the proposed network.",
            fontsize=11,
        )
        page.insert_text((50, 450), f"As shown in Fig. {index + 1}, the architecture contains an encoder.")
    document.save(path)
    document.close()


def test_extracts_caption_bbox_stable_id_and_canonical_preview(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_figure_pdf(pdf)
    settings = VisionSettings.from_env(False).model_copy(update={"cache_path": str(tmp_path / "cache.sqlite3")})
    paper = {"sections": [{"name": "method", "title": "Method", "page_start": 1, "page_end": 1}]}

    first = extract_paper_figures(pdf, tmp_path / "out-a", paper, settings)
    second = extract_paper_figures(pdf, tmp_path / "out-b", paper, settings)

    assert first["extraction_status"] == "success"
    assert len(first["figures"]) == 1
    figure = first["figures"][0]
    assert figure["figure_id"] == second["figures"][0]["figure_id"]
    assert figure["figure_id"].startswith("fig_")
    assert figure["caption"]["normalized_label"] == "1"
    assert figure["page_width"] == 600
    assert figure["page_height"] == 800
    assert len(figure["bbox"]) == len(figure["normalized_bbox"]) == 4
    assert all(0 <= value <= 1 for value in figure["normalized_bbox"])
    preview = figure["canonical_preview"]
    assert preview["source"] == "figure_bbox_render"
    assert Path(preview["path"]).exists()
    assert preview["width"] > 0 and preview["height"] > 0
    assert first["page_text_index"][0]["figure_references"]
    assert first["figure_reference_count"]["1"] == 1
    assert figure["reference_count"] == 1


def test_pdf_page_limit_preserves_completed_results(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_figure_pdf(pdf, pages=2)
    settings = VisionSettings.from_env(False).model_copy(update={"paper_max_pages": 1})

    result = extract_paper_figures(pdf, tmp_path / "out", {"sections": []}, settings)

    assert result["figures"]
    assert all(item["page_number"] == 1 for item in result["figures"])
    assert any(item["code"] == "paper_max_pages_exceeded" for item in result["warnings"])


def test_chinese_caption_variants_are_detected():
    blocks = [
        {"bbox": (10, 10, 100, 30), "text": "图 1 模型结构"},
        {"bbox": (10, 40, 100, 60), "text": "图1：整体流程"},
        {"bbox": (10, 70, 100, 90), "text": "图 2a 子模块"},
    ]

    captions = _caption_blocks(blocks)

    assert [item["normalized_label"] for item in captions] == ["1", "1", "2a"]
    assert [match.group("label") for match in REFERENCE_PATTERN.finditer("参见图 1、图1：以及图 2a")] == ["1", "1", "2a"]


def test_caption_above_figure_uses_lower_visual_region():
    import fitz

    bbox = _figure_bbox(
        fitz.Rect(0, 0, 600, 800),
        (80, 80, 520, 110),
        [],
        [(100, 140, 500, 340)],
        0,
    )

    assert bbox[1] <= 80
    assert bbox[3] >= 340
