from __future__ import annotations

from pathlib import Path

from backend.app.tools.paper_parse_tool import parse_paper_pdf
from backend.app.config.pdf_safety import PDFSafetySettings


def _write_sample_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "SimpleNet: A Tiny Classifier Head for Demo Alignment",
                "Abstract",
                "We propose a novel SimpleNet classifier head with relu activation for compact examples.",
                "Introduction",
                "The contribution is a small framework for explaining code alignment.",
                "Method",
                "Our method uses a SimpleNet module, a classifier head, and relu activation.",
            ]
        ),
    )
    document.save(path)
    document.close()


def _write_background_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "Generic Architecture Survey",
                "Abstract",
                "This paper presents a framework for understanding existing neural network architecture.",
                "Introduction",
                "The architecture is based on common background observations from prior work.",
                "Method",
                "The framework organizes baseline model components for discussion.",
            ]
        ),
    )
    document.save(path)
    document.close()


def test_parse_paper_pdf_extracts_basic_fields(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    _write_sample_pdf(pdf_path)

    analysis = parse_paper_pdf(pdf_path)

    assert analysis.paper_provided is True
    assert analysis.title == "SimpleNet: A Tiny Classifier Head for Demo Alignment"
    assert analysis.abstract and "SimpleNet classifier head" in analysis.abstract
    assert analysis.method_text and "SimpleNet module" in analysis.method_text
    assert analysis.contributions
    assert any("simplenet" in contribution.keywords for contribution in analysis.contributions)
    assert any(keyword.text == "simplenet" for keyword in analysis.keywords)
    assert "SimpleNet" in analysis.module_names
    assert analysis.page_count == 1
    assert analysis.raw_text_char_count > 0


def test_parse_paper_pdf_keeps_generic_background_low_confidence(tmp_path):
    pdf_path = tmp_path / "background.pdf"
    _write_background_pdf(pdf_path)

    analysis = parse_paper_pdf(pdf_path)

    assert all(contribution.confidence != "high" for contribution in analysis.contributions)
    assert all(
        any("启发式候选" in evidence for evidence in contribution.evidence)
        for contribution in analysis.contributions
    )


def test_parse_paper_pdf_missing_file_returns_error(tmp_path):
    analysis = parse_paper_pdf(tmp_path / "missing.pdf")

    assert analysis.paper_provided is True
    assert analysis.errors
    assert analysis.confidence == "low"


def test_parse_paper_pdf_respects_page_limit_and_keeps_partial_text(tmp_path):
    import fitz

    pdf_path = tmp_path / "many-pages.pdf"
    document = fitz.open()
    for index in range(3):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {index + 1} unique text")
    document.save(pdf_path)
    document.close()
    settings = PDFSafetySettings(max_file_bytes=1_000_000, max_pages=2, max_text_chars=10_000, parse_timeout_seconds=10)

    analysis = parse_paper_pdf(pdf_path, settings)

    assert analysis.page_count == 2
    assert analysis.raw_text_char_count > 0
    assert any("PAPER_MAX_PAGES" in warning for warning in analysis.warnings)


def test_parse_paper_pdf_stops_at_text_character_limit(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    _write_sample_pdf(pdf_path)
    settings = PDFSafetySettings(max_file_bytes=1_000_000, max_pages=10, max_text_chars=80, parse_timeout_seconds=10)

    analysis = parse_paper_pdf(pdf_path, settings)

    assert analysis.raw_text_char_count <= 80
    assert any("PAPER_MAX_TEXT_CHARS" in warning for warning in analysis.warnings)
