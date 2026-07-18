from __future__ import annotations

import re
from collections.abc import Sequence

from backend.app.domain.index_manifest import SymbolChunk
from backend.app.retrieval.schemas import QueryType


class EntityChunkSelector:
    def __init__(
        self,
        *,
        edge_evidence_lines: dict[str, set[int]] | None = None,
        current_hit_ranks: dict[str, int] | None = None,
    ) -> None:
        self.edge_evidence_lines = edge_evidence_lines or {}
        self.current_hit_ranks = current_hit_ranks or {}
        self.last_rule: str | None = None

    def select(
        self,
        *,
        entity_id: str,
        query_text: str,
        query_profile: QueryType,
        graph_path_edge_ids: Sequence[str],
        available_chunks: Sequence[SymbolChunk],
    ) -> SymbolChunk | None:
        chunks = [chunk for chunk in available_chunks if chunk.entity_id == entity_id]
        if not chunks:
            self.last_rule = "note_only"
            return None
        query_terms = _query_terms(query_text)
        evidence_lines = set().union(*(self.edge_evidence_lines.get(edge, set()) for edge in graph_path_edge_ids))
        ranked = sorted(
            chunks,
            key=lambda chunk: (
                -int(_contains_evidence_line(chunk, evidence_lines)),
                -int(_contains_query(chunk, query_terms)),
                self.current_hit_ranks.get(chunk.id, 10**9),
                _profile_priority(query_profile, chunk),
                chunk.ordinal,
                chunk.id,
            ),
        )
        selected = ranked[0]
        if _contains_evidence_line(selected, evidence_lines):
            self.last_rule = "graph_edge_evidence"
        elif _contains_query(selected, query_terms):
            self.last_rule = "exact_query_term"
        elif selected.id in self.current_hit_ranks:
            self.last_rule = "current_retrieval_hit"
        else:
            self.last_rule = "canonical_then_stable_id"
        return selected


def _profile_priority(profile: QueryType, chunk: SymbolChunk) -> tuple[int, int]:
    preferred: dict[QueryType, tuple[str, ...]] = {
        "symbol_lookup": ("function", "method", "class", "model_module", "file", "paper_entity"),
        "implementation_explanation": ("function", "method", "model_module", "class", "file", "paper_entity"),
        "call_chain": ("function", "method", "model_module", "class", "file", "paper_entity"),
        "architecture": ("class", "file", "model_module", "function", "method", "paper_entity"),
        "configuration": ("file", "function", "method", "class", "model_module", "paper_entity"),
        "paper_alignment": ("paper_entity", "function", "method", "class", "file", "model_module"),
        "tensor_shape": ("function", "method", "model_module", "class", "file", "paper_entity"),
        "training_process": ("function", "method", "file", "class", "model_module", "paper_entity"),
        "inference_process": ("function", "method", "file", "class", "model_module", "paper_entity"),
        "general_repository": ("class", "file", "function", "method", "model_module", "paper_entity"),
    }
    order = preferred[profile]
    return (order.index(chunk.chunk_type) if chunk.chunk_type in order else len(order), _line_span(chunk))


def _contains_evidence_line(chunk: SymbolChunk, lines: set[int]) -> bool:
    if chunk.start_line is None or chunk.end_line is None:
        return False
    return any(chunk.start_line <= line <= chunk.end_line for line in lines)


def _contains_query(chunk: SymbolChunk, terms: set[str]) -> bool:
    text = chunk.text.casefold()
    return bool(terms) and any(term in text for term in terms)


def _query_terms(text: str) -> set[str]:
    return {term.casefold() for term in re.findall(r"[A-Za-z_][\w.]*|[\u3400-\u9fff]{2,}", text)}


def _line_span(chunk: SymbolChunk) -> int:
    if chunk.start_line is None or chunk.end_line is None:
        return 10**9
    return chunk.end_line - chunk.start_line
