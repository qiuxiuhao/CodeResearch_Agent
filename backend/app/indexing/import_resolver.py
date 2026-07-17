from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.evidence import EvidenceRef
from backend.app.indexing.stable_ids import evidence_id, knowledge_edge_id, text_content_hash
from backend.app.indexing.symbol_table_builder import SymbolCandidate, SymbolTable, select_candidates


@dataclass(frozen=True)
class ResolvedImport:
    file_path: str
    local_name: str
    requested_name: str
    target_qualified_name: str
    target: SymbolCandidate | None
    resolution_type: str
    line_no: int | None


def resolve_imports(
    *,
    repo_id: str,
    parsed_files: list[dict],
    table: SymbolTable,
    module_roots: list[str],
) -> tuple[dict[str, dict[str, ResolvedImport]], list[KnowledgeEdge], list[EvidenceRef]]:
    bindings: dict[str, dict[str, ResolvedImport]] = {}
    edges: list[KnowledgeEdge] = []
    evidence: list[EvidenceRef] = []
    file_entities = {entity.path: entity for entity in table.entities_by_id.values() if entity.entity_type in {
        "file", "config", "training_entry", "inference_entry", "dataset"
    }}
    for parsed in parsed_files:
        path = parsed.get("file_path", "")
        source = file_entities.get(path)
        if source is None:
            continue
        current_module = source.module_name or source.qualified_name
        is_package = path.endswith("/__init__.py") or path == "__init__.py"
        file_bindings: dict[str, ResolvedImport] = {}
        for item in parsed.get("imports", []):
            requested, local_name = _requested_name(item, current_module, is_package)
            candidates = _import_candidates(requested, table)
            target, resolution = select_candidates(candidates)
            if item.get("alias"):
                resolution = "alias" if target else resolution
            elif str(item.get("module", "")).startswith(".") and target:
                resolution = "relative"
            resolved = ResolvedImport(
                file_path=path,
                local_name=local_name,
                requested_name=_display_requested(item),
                target_qualified_name=requested,
                target=target,
                resolution_type=resolution,
                line_no=item.get("line_no"),
            )
            file_bindings[local_name] = resolved
            ev = EvidenceRef(
                id=evidence_id("code", f"{path}:{item.get('line_no')}:{requested}", text_content_hash(requested)),
                source_type="code",
                entity_id=source.id,
                file_path=path,
                start_line=item.get("line_no"),
                end_line=item.get("line_no"),
                content_hash=text_content_hash(requested),
            )
            edge = KnowledgeEdge(
                id=knowledge_edge_id(source.id, "IMPORTS", target.entity_id if target else requested),
                repo_id=repo_id,
                source_id=source.id,
                target_id=target.entity_id if target else None,
                edge_type="IMPORTS",
                confidence=1.0 if target else (0.5 if resolution == "ambiguous" else 0.2),
                resolution_type=resolution,
                unresolved_symbol=None if target else requested,
                evidence_refs=[ev.id],
                metadata={"local_name": local_name, "requested_name": resolved.requested_name},
            )
            evidence.append(ev)
            edges.append(edge)
        bindings[path] = file_bindings
    return bindings, _merge_edges(edges), _dedupe_evidence(evidence)


def resolve_relative_module(module: str, current_module: str, is_package: bool) -> str:
    level = len(module) - len(module.lstrip("."))
    suffix = module[level:]
    if level == 0:
        return module
    package_parts = current_module.split(".") if is_package else current_module.split(".")[:-1]
    climb = level - 1
    if climb > len(package_parts):
        return module
    base = package_parts[: len(package_parts) - climb]
    if suffix:
        base.extend(part for part in suffix.split(".") if part)
    return ".".join(base)


def _requested_name(item: dict, current_module: str, is_package: bool) -> tuple[str, str]:
    module = str(item.get("module", ""))
    resolved_module = resolve_relative_module(module, current_module, is_package)
    name = item.get("name")
    if item.get("import_type") == "from_import" and name and name != "*":
        qualified = f"{resolved_module}.{name}" if resolved_module else str(name)
        local = item.get("alias") or name
        return qualified, str(local)
    local = item.get("alias") or module.lstrip(".").split(".", 1)[0]
    return resolved_module, str(local)


def _display_requested(item: dict) -> str:
    module = str(item.get("module", ""))
    name = item.get("name")
    return f"{module}.{name}" if name else module


def _import_candidates(qualified: str, table: SymbolTable) -> list[SymbolCandidate]:
    values = [*table.resolve(qualified), *table.modules.get(qualified, [])]
    return list({item.entity_id: item for item in values}.values())


def _merge_edges(items: list[KnowledgeEdge]) -> list[KnowledgeEdge]:
    merged: dict[str, KnowledgeEdge] = {}
    for item in items:
        existing = merged.get(item.id)
        if existing is None:
            merged[item.id] = item
        else:
            existing.evidence_refs = list(dict.fromkeys([*existing.evidence_refs, *item.evidence_refs]))
    return list(merged.values())


def _dedupe_evidence(items: list[EvidenceRef]) -> list[EvidenceRef]:
    return list({item.id: item for item in items}.values())
