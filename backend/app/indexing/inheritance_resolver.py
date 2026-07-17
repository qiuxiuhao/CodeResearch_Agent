from __future__ import annotations

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.evidence import EvidenceRef
from backend.app.indexing.import_resolver import ResolvedImport
from backend.app.indexing.stable_ids import evidence_id, knowledge_edge_id, text_content_hash
from backend.app.indexing.symbol_table_builder import SymbolTable, select_candidates


def build_inheritance_edges(
    repo_id: str,
    table: SymbolTable,
    import_bindings: dict[str, dict[str, ResolvedImport]],
) -> tuple[list[KnowledgeEdge], list[EvidenceRef]]:
    edges: list[KnowledgeEdge] = []
    evidence: list[EvidenceRef] = []
    for entity in table.entities_by_id.values():
        if entity.entity_type != "class":
            continue
        for base in entity.metadata.get("base_classes", []):
            if not isinstance(base, str) or not base:
                continue
            root, _, suffix = base.partition(".")
            binding = import_bindings.get(entity.path, {}).get(root)
            requested = f"{binding.target_qualified_name}.{suffix}" if binding and suffix else (
                binding.target_qualified_name if binding else f"{entity.module_name}.{base}"
            )
            target, resolution = select_candidates(table.resolve(requested))
            if target is None and not binding:
                target, resolution = select_candidates(table.by_short_name.get(base, []))
            ev = EvidenceRef(
                id=evidence_id("code", f"{entity.path}:{entity.start_line}:inherits:{base}", text_content_hash(base)),
                source_type="code",
                entity_id=entity.id,
                file_path=entity.path,
                start_line=entity.start_line,
                end_line=entity.start_line,
                content_hash=text_content_hash(base),
            )
            edges.append(KnowledgeEdge(
                id=knowledge_edge_id(entity.id, "INHERITS", target.entity_id if target else base),
                repo_id=repo_id,
                source_id=entity.id,
                target_id=target.entity_id if target else None,
                edge_type="INHERITS",
                confidence=1.0 if target else 0.2,
                resolution_type=resolution,
                unresolved_symbol=None if target else base,
                evidence_refs=[ev.id],
            ))
            evidence.append(ev)
    return edges, evidence
