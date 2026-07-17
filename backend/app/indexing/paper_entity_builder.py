from __future__ import annotations

from backend.app.domain.entities import PaperEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.indexing.stable_ids import evidence_id, paper_entity_id, paper_id_from_hash, text_content_hash


def build_paper_entities(
    paper_analysis: dict,
    figure_analysis: dict,
    paper_content_hash: str | None,
) -> tuple[str | None, list[PaperEntity], list[EvidenceRef]]:
    if not paper_analysis.get("paper_provided"):
        return None, [], []
    digest = paper_content_hash or text_content_hash(str(paper_analysis))
    paper_id = paper_id_from_hash(digest)
    entities: list[PaperEntity] = []
    evidence: list[EvidenceRef] = []

    for ordinal, section in enumerate(paper_analysis.get("sections", []), start=1):
        text = section.get("text", "")
        entity = _paper_entity(
            paper_id, "section", f"section:{section.get('page_start')}:{ordinal}", ordinal,
            section.get("title"), text, section.get("page_start"), None,
            keywords=[], module_names=[], metadata={"section_name": section.get("name"), "page_end": section.get("page_end")},
        )
        _attach_evidence(entity, evidence, "paper")
        entities.append(entity)

    for ordinal, contribution in enumerate(paper_analysis.get("contributions", []), start=1):
        text = contribution.get("description", "")
        locator = contribution.get("id") or f"contribution:{ordinal}"
        entity = _paper_entity(
            paper_id, "contribution", locator, ordinal, contribution.get("title"), text,
            contribution.get("page_no"), None,
            keywords=contribution.get("keywords", []), module_names=paper_analysis.get("module_names", []),
            metadata={"legacy_contribution_id": contribution.get("id"), "confidence": contribution.get("confidence")},
        )
        _attach_evidence(entity, evidence, "paper")
        entities.append(entity)

    for ordinal, figure in enumerate(figure_analysis.get("figures", []), start=1):
        caption = figure.get("caption", {})
        locator = figure.get("figure_id") or f"figure:{figure.get('page_number')}:{ordinal}"
        entity = _paper_entity(
            paper_id, "figure", locator, ordinal, caption.get("label"), caption.get("text", ""),
            figure.get("page_number"), figure.get("bbox"), keywords=[], module_names=[],
            metadata={"figure_id": figure.get("figure_id"), "section_name": figure.get("section_name")},
        )
        preview = figure.get("canonical_preview") or {}
        entity.figure_path = preview.get("path")
        _attach_evidence(entity, evidence, "figure", figure_id=figure.get("figure_id"))
        entities.append(entity)
    return paper_id, entities, evidence


def _paper_entity(
    paper_id: str,
    entity_type: str,
    locator: str,
    ordinal: int,
    title: str | None,
    text: str,
    page_number: int | None,
    bbox: list[float] | tuple[float, ...] | None,
    *,
    keywords: list[str],
    module_names: list[str],
    metadata: dict,
) -> PaperEntity:
    normalized_bbox = tuple(bbox) if bbox and len(bbox) == 4 else None
    return PaperEntity(
        id=paper_entity_id(paper_id, entity_type, str(locator), ordinal),
        paper_id=paper_id,
        entity_type=entity_type,
        title=title,
        text=text,
        page_number=page_number,
        bbox=normalized_bbox,
        keywords=keywords,
        module_names=module_names,
        content_hash=text_content_hash(text),
        metadata=metadata,
    )


def _attach_evidence(
    entity: PaperEntity,
    evidence: list[EvidenceRef],
    source_type: str,
    *,
    figure_id: str | None = None,
) -> None:
    locator = f"{entity.paper_id}:{entity.page_number}:{figure_id or entity.id}"
    item = EvidenceRef(
        id=evidence_id(source_type, locator, entity.content_hash),
        source_type=source_type,
        entity_id=entity.id,
        paper_id=entity.paper_id,
        page_number=entity.page_number,
        figure_id=figure_id,
        bbox=entity.bbox,
        content_hash=entity.content_hash,
    )
    entity.evidence_refs.append(item.id)
    evidence.append(item)
