from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

from backend.app.schemas.paper import PaperAnalysis, PaperContribution, PaperKeyword, PaperSection
from backend.app.config.pdf_safety import PDFSafetySettings


SECTION_ALIASES = {
    "abstract": "abstract",
    "introduction": "introduction",
    "contributions": "contributions",
    "contribution": "contributions",
    "method": "method",
    "methods": "method",
    "approach": "method",
    "proposed method": "method",
    "model": "method",
    "architecture": "method",
    "experiments": "experiments",
    "results": "results",
    "conclusion": "conclusion",
}
STRONG_CONTRIBUTION_PATTERNS = (
    "we propose",
    "we introduce",
    "we design",
    "we develop",
    "our contribution",
    "novel",
    "new module",
    "new framework",
)
WEAK_CONTRIBUTION_PATTERNS = (
    "we present",
    "paper presents",
    "contribution",
    "framework",
    "module",
    "architecture",
    "loss",
    "encoder",
    "decoder",
    "backbone",
    "head",
)
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "our",
    "into",
    "using",
    "method",
    "model",
    "network",
    "paper",
    "approach",
    "based",
    "learning",
    "deep",
    "propose",
    "present",
    "introduce",
}


def empty_paper_analysis(warning: str = "未提供论文 PDF，跳过论文解析。") -> PaperAnalysis:
    return PaperAnalysis(
        paper_provided=False,
        warnings=[warning],
        confidence="low",
    )


def parse_paper_pdf(
    paper_pdf_path: str | Path,
    safety_settings: PDFSafetySettings | None = None,
) -> PaperAnalysis:
    path = Path(paper_pdf_path)
    settings = safety_settings or PDFSafetySettings.from_env()
    if not path.exists():
        return _error_analysis(path, "FileNotFoundError", f"Paper PDF not found: {path}")
    try:
        if path.stat().st_size > settings.max_file_bytes:
            return PaperAnalysis(
                paper_provided=True,
                paper_path=str(path),
                warnings=["论文文件超过 PAPER_MAX_FILE_BYTES，已跳过论文文本解析。"],
                confidence="low",
            )
    except OSError as exc:
        return _error_analysis(path, type(exc).__name__, "Unable to inspect paper PDF.")

    try:
        pages, safety_warnings = _extract_pdf_pages(path, settings)
    except Exception as exc:
        return _error_analysis(path, type(exc).__name__, str(exc))

    full_text = "\n".join(page["text"] for page in pages).strip()
    if not full_text:
        analysis = PaperAnalysis(
            paper_provided=True,
            paper_path=str(path),
            page_count=len(pages),
            raw_text_char_count=0,
            warnings=[*safety_warnings, "PDF 未提取到文本，可能是扫描版或图片型论文。"],
            confidence="low",
        )
        return analysis

    sections = _extract_sections(full_text, pages)
    title = _extract_title(pages)
    abstract = _extract_abstract(sections, full_text)
    method_text = _extract_method_text(sections)
    contributions = _extract_contributions(sections, abstract)
    keywords = _extract_keywords(title, abstract, method_text, contributions)
    module_names = _extract_module_names(full_text)
    warnings: list[str] = list(safety_warnings)
    if not contributions:
        warnings.append("未找到明显论文创新点候选。")
    if not sections:
        warnings.append("未识别到标准章节标题，已使用全文启发式提取。")

    return PaperAnalysis(
        paper_provided=True,
        paper_path=str(path),
        title=title,
        abstract=abstract,
        method_text=method_text,
        sections=sections,
        contributions=contributions,
        keywords=keywords,
        module_names=module_names,
        raw_text_char_count=len(full_text),
        page_count=len(pages),
        warnings=warnings,
        confidence="medium" if full_text else "low",
    )


def _extract_pdf_pages(path: Path, settings: PDFSafetySettings) -> tuple[list[dict], list[str]]:
    import fitz

    pages: list[dict] = []
    warnings: list[str] = []
    started = time.monotonic()
    text_chars = 0
    with fitz.open(path) as document:
        page_limit = min(document.page_count, settings.max_pages)
        if document.page_count > page_limit:
            warnings.append(f"论文超过 PAPER_MAX_PAGES，仅解析前 {page_limit} 页。")
        for index in range(page_limit):
            if time.monotonic() - started >= settings.parse_timeout_seconds:
                warnings.append("论文文本解析达到 PAPER_PARSE_TIMEOUT_SECONDS，已保留完成结果。")
                break
            text = document[index].get_text("text")
            remaining = settings.max_text_chars - text_chars
            if remaining <= 0:
                warnings.append("论文文本达到 PAPER_MAX_TEXT_CHARS，已保留截断结果。")
                break
            if len(text) > remaining:
                text = text[:remaining]
                pages.append({"page_no": index + 1, "text": text})
                text_chars += len(text)
                warnings.append("论文文本达到 PAPER_MAX_TEXT_CHARS，已保留截断结果。")
                break
            pages.append({"page_no": index + 1, "text": text})
            text_chars += len(text)
            if time.monotonic() - started >= settings.parse_timeout_seconds:
                warnings.append("论文文本解析达到 PAPER_PARSE_TIMEOUT_SECONDS，已保留完成结果。")
                break
    return pages, warnings


def _extract_title(pages: list[dict]) -> str | None:
    if not pages:
        return None
    for line in _nonempty_lines(pages[0]["text"]):
        normalized = _clean_line(line)
        if normalized.lower() not in SECTION_ALIASES and len(normalized) > 5:
            return normalized
    return None


def _extract_sections(full_text: str, pages: list[dict]) -> list[PaperSection]:
    lines = full_text.splitlines()
    sections: list[PaperSection] = []
    current_title: str | None = None
    current_name: str | None = None
    current_lines: list[str] = []

    for line in lines:
        cleaned = _clean_line(line)
        section_name = _section_name(cleaned)
        if section_name:
            if current_title and current_name:
                sections.append(_section_from_lines(current_name, current_title, current_lines, pages))
            current_title = cleaned
            current_name = section_name
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)

    if current_title and current_name:
        sections.append(_section_from_lines(current_name, current_title, current_lines, pages))
    return sections


def _extract_abstract(sections: list[PaperSection], full_text: str) -> str | None:
    for section in sections:
        if section.name == "abstract":
            return _trim_text(section.text, 1500)
    match = re.search(r"abstract\s+(.*?)(?:\n\s*(?:1\s+)?introduction\b|\n\s*method\b)", full_text, re.I | re.S)
    if match:
        return _trim_text(match.group(1), 1500)
    return None


def _extract_method_text(sections: list[PaperSection]) -> str | None:
    method_sections = [section.text for section in sections if section.name == "method"]
    if not method_sections:
        return None
    return _trim_text("\n".join(method_sections), 4000)


def _extract_contributions(sections: list[PaperSection], abstract: str | None) -> list[PaperContribution]:
    candidate_sources: list[tuple[str, str, int | None]] = []
    for section in sections:
        if section.name in {"abstract", "introduction", "contributions", "method"}:
            candidate_sources.append((section.name, section.text, section.page_start))
    if abstract:
        candidate_sources.insert(0, ("abstract", abstract, None))

    contributions: list[PaperContribution] = []
    seen: set[str] = set()
    for section_name, text, page_no in candidate_sources:
        for sentence in _split_sentences(text):
            normalized = sentence.lower()
            match_kind = _contribution_match_kind(normalized)
            if not match_kind:
                continue
            cleaned = _trim_text(sentence, 600)
            dedupe_key = re.sub(r"\W+", " ", cleaned.lower()).strip()
            if not cleaned or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            contributions.append(
                PaperContribution(
                    id=f"C{len(contributions) + 1}",
                    title=_contribution_title(cleaned),
                    description=cleaned,
                    source_section=section_name,
                    page_no=page_no,
                    keywords=_keywords_from_text(cleaned, 8),
                    evidence=_contribution_evidence(section_name, cleaned, match_kind),
                    confidence=_contribution_confidence(section_name, match_kind),
                )
            )
            if len(contributions) >= 5:
                return contributions
    return contributions


def _extract_keywords(
    title: str | None,
    abstract: str | None,
    method_text: str | None,
    contributions: list[PaperContribution],
) -> list[PaperKeyword]:
    keywords: list[PaperKeyword] = []
    seen: set[str] = set()

    def add_keyword(text: str, source: str, evidence: str) -> None:
        key = text.lower()
        if key in seen or len(text) < 3:
            return
        seen.add(key)
        keywords.append(PaperKeyword(text=text, source=source, evidence=[evidence]))  # type: ignore[arg-type]

    for source_name, text in (("title", title), ("abstract", abstract), ("method", method_text)):
        if not text:
            continue
        for keyword in _keywords_from_text(text, 12):
            add_keyword(keyword, source_name, f"来自 {source_name} 文本。")
    for contribution in contributions:
        for keyword in contribution.keywords:
            add_keyword(keyword, "contribution", f"来自创新点 {contribution.id}。")

    corpus = " ".join(item for item in [title, abstract, method_text] if item)
    for word, _count in Counter(_tokenize(corpus)).most_common(30):
        if len(keywords) >= 30:
            break
        add_keyword(word, "frequency", "来自论文文本高频词。")
    return keywords[:30]


def _extract_module_names(text: str) -> list[str]:
    candidates = re.findall(
        r"\b[A-Z][A-Za-z0-9]*(?:Module|Net|Network|Encoder|Decoder|Backbone|Head|Loss)\b",
        text,
    )
    lowered = text.lower()
    for word in ("encoder", "decoder", "backbone", "attention", "transformer", "fusion", "contrastive", "loss", "head"):
        if word in lowered:
            candidates.append(word)
    return _dedupe_preserve_order(candidates)[:20]


def _section_from_lines(name: str, title: str, lines: list[str], pages: list[dict]) -> PaperSection:
    text = _trim_text("\n".join(lines).strip(), 5000)
    page_no = _find_text_page(title, pages)
    return PaperSection(
        name=name,
        title=title,
        text=text,
        page_start=page_no,
        page_end=page_no,
        evidence=[f"识别章节标题：{title}"],
    )


def _section_name(line: str) -> str | None:
    normalized = re.sub(r"^\d+(\.\d+)*\s+", "", line.strip().lower())
    normalized = normalized.rstrip(":")
    return SECTION_ALIASES.get(normalized)


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text)
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", normalized) if item.strip()]


def _contribution_title(sentence: str) -> str:
    words = _keywords_from_text(sentence, 10)
    return " ".join(words[:10]) or _trim_text(sentence, 80)


def _contribution_match_kind(sentence_lower: str) -> str | None:
    if any(pattern in sentence_lower for pattern in STRONG_CONTRIBUTION_PATTERNS):
        return "strong"

    weak_hits = [pattern for pattern in WEAK_CONTRIBUTION_PATTERNS if pattern in sentence_lower]
    if not weak_hits:
        return None

    specific_hits = set(weak_hits) - {"we present", "paper presents", "framework", "architecture"}
    if specific_hits:
        return "weak"

    contextual_marker = any(
        marker in sentence_lower
        for marker in ("we present", "paper presents", "our ", "proposed", "new ")
    )
    if contextual_marker:
        return "weak"
    return None


def _contribution_evidence(section_name: str, sentence: str, match_kind: str) -> list[str]:
    evidence = [f"{section_name} 中句子：{sentence}"]
    if match_kind == "strong":
        evidence.append("命中强创新点关键词，作为核心创新点候选。")
    else:
        evidence.append("启发式候选：仅命中弱创新点表达，置信度保持为 low。")
    return evidence


def _contribution_confidence(section_name: str, match_kind: str) -> str:
    if match_kind != "strong":
        return "low"
    if section_name in {"abstract", "contributions", "method"}:
        return "high"
    if section_name == "introduction":
        return "medium"
    return "low"


def _keywords_from_text(text: str, limit: int) -> list[str]:
    return _dedupe_preserve_order(_tokenize(text))[:limit]


def _tokenize(text: str) -> list[str]:
    original_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+-]*", text.replace("_", " "))
    raw_tokens = [*original_tokens, *re.findall(r"[A-Za-z][A-Za-z0-9_+-]*", _split_camel(text))]
    result: list[str] = []
    for token in raw_tokens:
        normalized = token.lower().strip("_")
        if len(normalized) < 3 or normalized in STOPWORDS:
            continue
        if normalized.endswith("s") and len(normalized) > 4:
            normalized = normalized[:-1]
        result.append(normalized)
    return result


def _split_camel(text: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text.replace("_", " "))


def _find_text_page(text: str, pages: list[dict]) -> int | None:
    if not text:
        return None
    needle = text.lower()
    for page in pages:
        if needle in page.get("text", "").lower():
            return page.get("page_no")
    return None


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _trim_text(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _error_analysis(path: Path, error_type: str, message: str) -> PaperAnalysis:
    error = {
        "tool": "paper_parse_tool",
        "path": str(path),
        "error_type": error_type,
        "message": message,
    }
    return PaperAnalysis(
        paper_provided=True,
        paper_path=str(path),
        errors=[error],
        confidence="low",
    )
