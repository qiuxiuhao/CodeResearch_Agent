from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping, Sequence

from backend.app.retrieval.schemas import ContextBundle, ContextItem, RetrievalCandidate, RetrievalEvidence


def conservative_code_token_count(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = len(text) - cjk
    return max(1, cjk + math.ceil(non_cjk / 2.5)) if text else 0


class ContextBuilder:
    def build(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        query_id: str,
        query_text: str,
        candidates: Sequence[RetrievalCandidate],
        token_budget: int,
        max_entities: int,
        relationship_notes: Mapping[str, Sequence[str]] | None = None,
    ) -> ContextBundle:
        notes = relationship_notes or {}
        warnings: list[str] = []
        omitted: list[str] = []
        items: list[ContextItem] = []
        seen_hashes: set[str] = set()
        seen_entities: set[str] = set()
        per_item_limit = max(1, math.floor(token_budget * 0.4))
        for candidate in candidates:
            if candidate.content_hash in seen_hashes or candidate.entity_id in seen_entities:
                omitted.append(candidate.chunk_id)
                continue
            if len(seen_entities) >= max_entities:
                omitted.append(candidate.chunk_id)
                continue
            text = candidate.text
            estimated = conservative_code_token_count(text)
            truncated = False
            if estimated > per_item_limit:
                text = _query_aware_truncate(text, query_text, per_item_limit)
                estimated = conservative_code_token_count(text)
                truncated = text != candidate.text
            if sum(item.token_count for item in items) + estimated > token_budget:
                omitted.append(candidate.chunk_id)
                continue
            evidence = candidate.evidence or _fallback_evidence(candidate)
            items.append(ContextItem(
                context_id=_context_id(query_id, candidate.entity_id, candidate.chunk_id),
                entity_id=candidate.entity_id,
                chunk_ids=[candidate.chunk_id],
                title=candidate.qualified_name or candidate.path or candidate.entity_id,
                text=text,
                token_count=estimated,
                truncated=truncated,
                rank=len(items) + 1,
                relationship_notes=list(notes.get(candidate.entity_id, [])),
                evidence=evidence,
            ))
            seen_hashes.add(candidate.content_hash)
            seen_entities.add(candidate.entity_id)
        if not items and candidates:
            candidate = candidates[0]
            text = _query_aware_truncate(candidate.text, query_text, token_budget)
            count = conservative_code_token_count(text)
            items.append(ContextItem(
                context_id=_context_id(query_id, candidate.entity_id, candidate.chunk_id),
                entity_id=candidate.entity_id, chunk_ids=[candidate.chunk_id],
                title=candidate.qualified_name or candidate.path or candidate.entity_id,
                text=text, token_count=count, truncated=text != candidate.text, rank=1,
                relationship_notes=list(notes.get(candidate.entity_id, [])),
                evidence=candidate.evidence or _fallback_evidence(candidate),
            ))
            warnings.append("single_item_budget_override")
        return ContextBundle(
            repo_id=repo_id,
            index_version_id=index_version_id,
            query_id=query_id,
            items=items,
            estimated_tokens=sum(item.token_count for item in items),
            token_count_method="conservative_code_estimate",
            token_budget=token_budget,
            omitted_candidate_ids=omitted,
            warnings=warnings,
        )

    def validate_provider_budget(
        self,
        bundle: ContextBundle,
        *,
        prompt_token_counter: Callable[[Sequence[ContextItem]], int],
        provider_context_limit: int,
        reserved_output_tokens: int,
    ) -> ContextBundle:
        allowed = provider_context_limit - reserved_output_tokens
        if allowed < 0:
            raise ValueError("reserved_output_tokens exceeds the Provider context limit.")
        items = list(bundle.items)
        actual = prompt_token_counter(items)
        omitted = list(bundle.omitted_candidate_ids)
        while items and actual > allowed:
            removed = items.pop()
            omitted.extend(removed.chunk_ids)
            actual = prompt_token_counter(items)
        items = [item.model_copy(update={"rank": rank}) for rank, item in enumerate(items, 1)]
        warnings = list(bundle.warnings)
        if len(items) != len(bundle.items):
            warnings.append("provider_token_validation_reduced_context")
        return bundle.model_copy(update={
            "items": items,
            "provider_validated_tokens": actual,
            "token_count_method": "provider_tokenizer",
            "omitted_candidate_ids": omitted,
            "warnings": warnings,
        })


def _query_aware_truncate(text: str, query_text: str, budget: int) -> str:
    lines = text.splitlines()
    if conservative_code_token_count(text) <= budget:
        return text
    terms = [term.casefold() for term in re.findall(r"[A-Za-z_][\w.]*|[\u3400-\u9fff]{2,}", query_text)]
    indexes = [
        index for index, line in enumerate(lines)
        if any(term in line.casefold() for term in terms)
    ]
    selected = set(range(min(5, len(lines))))
    for index in indexes:
        selected.update(range(max(0, index - 20), min(len(lines), index + 21)))
    selected.update(range(max(0, len(lines) - 3), len(lines)))
    ordered = [lines[index] for index in sorted(selected)]
    while ordered and conservative_code_token_count("\n".join(ordered)) > budget:
        ordered.pop()
    if not ordered:
        max_chars = max(1, int(budget * 2.5))
        return text[:max_chars]
    return "\n".join(ordered)


def _fallback_evidence(candidate: RetrievalCandidate) -> list[RetrievalEvidence]:
    if candidate.path:
        return [RetrievalEvidence(
            evidence_id=f"chunk:{candidate.chunk_id}", source_type="code", path=candidate.path,
            start_line=candidate.start_line, end_line=candidate.end_line,
        )]
    if candidate.page_number is not None:
        return [RetrievalEvidence(
            evidence_id=f"chunk:{candidate.chunk_id}", source_type="paper", page_number=candidate.page_number,
        )]
    return []


def _context_id(query_id: str, entity_id: str, chunk_id: str) -> str:
    digest = hashlib.sha256(f"{query_id}\0{entity_id}\0{chunk_id}".encode("utf-8")).hexdigest()
    return f"ctx_{digest}"
