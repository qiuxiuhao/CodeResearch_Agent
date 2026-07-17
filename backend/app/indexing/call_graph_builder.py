from __future__ import annotations

import ast
from collections import defaultdict

from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.evidence import EvidenceRef
from backend.app.indexing.import_resolver import ResolvedImport
from backend.app.indexing.stable_ids import evidence_id, knowledge_edge_id, text_content_hash
from backend.app.indexing.symbol_table_builder import SymbolCandidate, SymbolTable, select_candidates


def build_call_edges(
    *,
    repo_id: str,
    functions: list[dict],
    table: SymbolTable,
    import_bindings: dict[str, dict[str, ResolvedImport]],
    module_roots: list[str],
) -> tuple[list[KnowledgeEdge], list[EvidenceRef]]:
    edges: list[KnowledgeEdge] = []
    evidence: list[EvidenceRef] = []
    instance_bindings = _instance_bindings(functions, table, import_bindings, module_roots)
    modules_by_path = {
        entity.path: entity.module_name or entity.qualified_name
        for entity in table.entities_by_id.values()
        if entity.entity_type in {"file", "config", "training_entry", "inference_entry", "dataset"}
    }
    for function in functions:
        source = function.get("source_code") or ""
        if not source:
            continue
        path = function.get("file_path", "")
        module_name = modules_by_path.get(path, path.removesuffix(".py").replace("/", "."))
        owner = function.get("class_name")
        qualified = f"{module_name}.{owner}.{function.get('function_name')}" if owner else f"{module_name}.{function.get('function_name')}"
        source_candidate, _ = select_candidates(table.resolve(qualified))
        if source_candidate is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            display = _node_text(call.func)
            target, resolution = _resolve_call(
                display, module_name, owner, path, table, import_bindings.get(path, {}), instance_bindings
            )
            edge_type = "INSTANTIATES" if target and target.entity_type == "class" else "CALLS"
            absolute_line = None
            if function.get("start_line") is not None and getattr(call, "lineno", None) is not None:
                absolute_line = function["start_line"] + call.lineno - 1
            ev = EvidenceRef(
                id=evidence_id("code", f"{path}:{absolute_line}:{source_candidate.entity_id}:{display}", text_content_hash(display)),
                source_type="code",
                entity_id=source_candidate.entity_id,
                file_path=path,
                start_line=absolute_line,
                end_line=absolute_line,
                content_hash=text_content_hash(display),
            )
            edges.append(KnowledgeEdge(
                id=knowledge_edge_id(source_candidate.entity_id, edge_type, target.entity_id if target else display),
                repo_id=repo_id,
                source_id=source_candidate.entity_id,
                target_id=target.entity_id if target else None,
                edge_type=edge_type,
                confidence=1.0 if target else (0.5 if resolution == "ambiguous" else 0.2),
                resolution_type=resolution,
                unresolved_symbol=None if target else display,
                evidence_refs=[ev.id],
                metadata={"call_expression": display},
            ))
            evidence.append(ev)
    return _merge_edges(edges), list({item.id: item for item in evidence}.values())


def build_structure_edges(repo_id: str, table: SymbolTable) -> list[KnowledgeEdge]:
    edges: list[KnowledgeEdge] = []
    for entity in table.entities_by_id.values():
        if not entity.parent_id:
            continue
        edge_type = "DEFINES" if entity.entity_type in {"class", "function", "method"} else "CONTAINS"
        edges.append(KnowledgeEdge(
            id=knowledge_edge_id(entity.parent_id, edge_type, entity.id),
            repo_id=repo_id,
            source_id=entity.parent_id,
            target_id=entity.id,
            edge_type=edge_type,
            confidence=1.0,
            resolution_type="exact",
            evidence_refs=list(entity.evidence_refs),
        ))
    return edges


def _resolve_call(
    display: str,
    module_name: str,
    owner: str | None,
    path: str,
    table: SymbolTable,
    bindings: dict[str, ResolvedImport],
    instance_bindings: dict[tuple[str, str], str],
) -> tuple[SymbolCandidate | None, str]:
    if owner and display.startswith("self."):
        member = display.removeprefix("self.")
        direct, resolution = select_candidates(table.resolve(f"{module_name}.{owner}.{member}"))
        if direct:
            return direct, "self_method"
        class_qualified = instance_bindings.get((f"{module_name}.{owner}", member))
        if class_qualified:
            forward, resolution = select_candidates(table.resolve(f"{class_qualified}.forward"))
            if forward:
                return forward, "model_forward"
            cls, resolution = select_candidates(table.resolve(class_qualified))
            if cls:
                return cls, resolution
    root, dot, suffix = display.partition(".")
    binding = bindings.get(root)
    if binding:
        requested = f"{binding.target_qualified_name}.{suffix}" if dot and suffix else binding.target_qualified_name
        target, resolution = select_candidates(table.resolve(requested))
        if target:
            return target, "alias" if root != binding.requested_name else resolution
        if binding.target and not dot:
            return binding.target, binding.resolution_type
    requested = f"{module_name}.{display}"
    target, resolution = select_candidates(table.resolve(requested))
    if target:
        return target, resolution
    short = table.by_short_name.get(display, []) if "." not in display else []
    return select_candidates(short)


def _instance_bindings(
    functions: list[dict],
    table: SymbolTable,
    import_bindings: dict[str, dict[str, ResolvedImport]],
    module_roots: list[str],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    modules_by_path = {
        entity.path: entity.module_name or entity.qualified_name
        for entity in table.entities_by_id.values()
        if entity.entity_type in {"file", "config", "training_entry", "inference_entry", "dataset"}
    }
    for function in functions:
        if function.get("function_name") != "__init__" or not function.get("class_name"):
            continue
        path = function.get("file_path", "")
        module = modules_by_path.get(path, path.removesuffix(".py").replace("/", "."))
        owner = f"{module}.{function['class_name']}"
        try:
            tree = ast.parse(function.get("source_code") or "")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            class_name = _node_text(value.func)
            resolved, _ = _resolve_call(class_name, module, function.get("class_name"), path, table, import_bindings.get(path, {}), {})
            if resolved is None or resolved.entity_type != "class":
                continue
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                    result[(owner, target.attr)] = resolved.qualified_name
    return result


def _node_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _merge_edges(items: list[KnowledgeEdge]) -> list[KnowledgeEdge]:
    merged: dict[str, KnowledgeEdge] = {}
    for item in items:
        if item.id not in merged:
            merged[item.id] = item
            continue
        current = merged[item.id]
        current.evidence_refs = list(dict.fromkeys([*current.evidence_refs, *item.evidence_refs]))
    return list(merged.values())
