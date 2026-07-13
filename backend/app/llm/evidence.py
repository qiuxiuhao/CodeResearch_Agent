from __future__ import annotations

from typing import Iterable

from backend.app.schemas.llm_explanation import EvidenceItem


def make_evidence(
    evidence_id: str,
    evidence_type: str,
    fact_summary: str,
    *,
    file_path: str | None = None,
    class_name: str | None = None,
    function_name: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    rule_field: str | None = None,
    confidence: str = "medium",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        file_path=file_path,
        class_name=class_name,
        function_name=function_name,
        start_line=start_line,
        end_line=end_line,
        rule_field=rule_field,
        fact_summary=fact_summary,
        confidence=confidence,
    )


def validate_evidence_refs(refs: Iterable[str], catalog: Iterable[EvidenceItem | dict]) -> bool:
    valid = {item.evidence_id if isinstance(item, EvidenceItem) else item.get("evidence_id") for item in catalog}
    return all(ref in valid for ref in refs)


def merge_evidence(existing: list[dict], additions: Iterable[EvidenceItem]) -> list[dict]:
    merged = {item.get("evidence_id"): item for item in existing}
    for item in additions:
        merged[item.evidence_id] = item.model_dump()
    return list(merged.values())
