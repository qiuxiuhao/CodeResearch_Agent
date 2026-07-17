from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path, PurePosixPath

from backend.app.domain.entities import CodeEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.indexing.module_roots import module_name_for_path
from backend.app.indexing.path_normalizer import normalize_index_path
from backend.app.indexing.stable_ids import code_entity_id, evidence_id, model_module_entity_id, text_content_hash


FILE_ROLE_ENTITY_TYPES = {
    "config_related": "config",
    "training": "training_entry",
    "inference": "inference_entry",
    "dataset": "dataset",
}


def build_code_entities(
    *,
    repo_id: str,
    repo_path: str | Path,
    parsed_files: list[dict],
    file_analysis: list[dict],
    model_analysis: list[dict],
    module_roots: list[str],
) -> tuple[list[CodeEntity], list[EvidenceRef]]:
    root = Path(repo_path)
    file_info = {item.get("file_path", ""): item for item in file_analysis}
    entities: list[CodeEntity] = []
    evidence: list[EvidenceRef] = []
    directory_ids: dict[str, str] = {}
    file_ids: dict[str, str] = {}
    class_ids: dict[tuple[str, str], list[tuple[int, int, str]]] = {}

    repository = _code_entity(repo_id, "repository", ".", root.name or "repository", root.name or "repository", "")
    repository_evidence = _code_evidence(repository, ".", None, None)
    repository.evidence_refs.append(repository_evidence.id)
    entities.append(repository)
    evidence.append(repository_evidence)

    paths = sorted(normalize_index_path(item.get("file_path", "")) for item in parsed_files if item.get("file_path"))
    for path in paths:
        _ensure_directories(repo_id, path, repository.id, directory_ids, entities, evidence)

    for parsed in sorted(parsed_files, key=lambda item: item.get("file_path", "")):
        path = normalize_index_path(parsed["file_path"])
        module_name, candidates = module_name_for_path(path, module_roots, root)
        source = _read_source(root / path)
        role = file_info.get(parsed["file_path"], {}).get("file_type", "ordinary_module")
        entity_type = FILE_ROLE_ENTITY_TYPES.get(role, "file")
        parent = directory_ids.get(PurePosixPath(path).parent.as_posix(), repository.id)
        item = _code_entity(
            repo_id, entity_type, path, PurePosixPath(path).name, module_name, source,
            parent_id=parent,
            module_name=module_name,
            metadata={
                "file_role": role,
                "module_candidates": candidates,
                "module_ambiguous": len(candidates) > 1,
                "module_unresolved": not candidates,
            },
        )
        file_ev = _code_evidence(item, path, None, None)
        item.evidence_refs.append(file_ev.id)
        entities.append(item)
        evidence.append(file_ev)
        file_ids[path] = item.id

        _append_declared_entities(
            repo_id, parsed, path, module_name, item.id, source, entities, evidence, class_ids
        )

    class_candidates: dict[tuple[str, str], list[CodeEntity]] = {}
    for entity in entities:
        if entity.entity_type == "class":
            class_candidates.setdefault((entity.path, entity.name), []).append(entity)
    by_class = {
        key: values[-1]
        for key, values in class_candidates.items()
        if len(values) == 1 or all(bool(item.metadata.get("duplicate_resolution_safe")) for item in values)
    }
    for model in model_analysis:
        path = normalize_index_path(model.get("file_path", ""))
        class_entity = by_class.get((path, model.get("class_name", "")))
        if class_entity is None:
            continue
        for layer in model.get("layers", []):
            name = layer.get("name") or layer.get("assigned_name", "").removeprefix("self.")
            if not name:
                continue
            qualified = f"{class_entity.qualified_name}.{name}"
            entity = _code_entity(
                repo_id, "model_module", path, name, qualified, layer.get("call_text", ""),
                parent_id=class_entity.id,
                module_name=class_entity.module_name,
                start_line=layer.get("line_no"),
                end_line=layer.get("line_no"),
                metadata={"layer_type": layer.get("layer_type", ""), "role": layer.get("role", "unknown")},
                entity_id=model_module_entity_id(repo_id, class_entity.id, name),
            )
            ev = _code_evidence(entity, path, entity.start_line, entity.end_line)
            entity.evidence_refs.append(ev.id)
            entities.append(entity)
            evidence.append(ev)
    return _dedupe_entities(entities), _dedupe_evidence(evidence)


def _append_declared_entities(
    repo_id: str,
    parsed: dict,
    path: str,
    module_name: str,
    file_id: str,
    file_source: str,
    entities: list[CodeEntity],
    evidence: list[EvidenceRef],
    class_ids: dict[tuple[str, str], list[tuple[int, int, str]]],
) -> None:
    declarations: list[tuple[str, str, dict]] = []
    for item in parsed.get("classes", []):
        declarations.append(("class", f"{module_name}.{item.get('class_name', '')}", item))
    for item in parsed.get("functions", []):
        owner = item.get("class_name")
        qualified = f"{module_name}.{owner}.{item.get('function_name', '')}" if owner else f"{module_name}.{item.get('function_name', '')}"
        declarations.append(("method" if owner else "function", qualified, item))
    counts = Counter((kind, qualified) for kind, qualified, _ in declarations)
    seen: Counter[tuple[str, str]] = Counter()
    declarations.sort(key=lambda value: (value[2].get("start_line") or 0, value[0], value[1]))
    unconditional = _unconditional_declarations(file_source)
    for kind, qualified, raw in declarations:
        key = (kind, qualified)
        seen[key] += 1
        ordinal = seen[key] if counts[key] > 1 else None
        name_key = "class_name" if kind == "class" else "function_name"
        parent_id = file_id
        if kind == "method":
            parent_id = _method_parent(
                class_ids.get((path, raw.get("class_name", "")), []), raw.get("start_line")
            ) or file_id
        source = raw.get("source_code") or _source_range(
            file_source, raw.get("start_line"), raw.get("end_line")
        )
        signature = None
        if kind in {"function", "method"}:
            signature = f"{raw.get('function_name', '')}({', '.join(raw.get('args', []))})"
        entity = _code_entity(
            repo_id, kind, path, raw.get(name_key, ""), qualified, source,
            parent_id=parent_id,
            module_name=module_name,
            start_line=raw.get("start_line"),
            end_line=raw.get("end_line"),
            signature=signature,
            docstring=_docstring(source),
            declaration_ordinal=ordinal,
            metadata={
                "duplicate_symbol": counts[key] > 1,
                "declaration_ordinal": ordinal,
                "duplicate_resolution_safe": (
                    kind, raw.get("class_name"), raw.get(name_key, ""), raw.get("start_line")
                ) in unconditional,
                "base_classes": raw.get("base_classes", []) if kind == "class" else [],
                "raw_call_expressions": raw.get("raw_call_expressions", []) if kind != "class" else [],
            },
        )
        ev = _code_evidence(entity, path, entity.start_line, entity.end_line)
        entity.evidence_refs.append(ev.id)
        entities.append(entity)
        evidence.append(ev)
        if kind == "class":
            class_ids.setdefault((path, entity.name), []).append((
                entity.start_line or 0, entity.end_line or 2**31 - 1, entity.id
            ))


def _ensure_directories(
    repo_id: str,
    path: str,
    repository_id: str,
    directory_ids: dict[str, str],
    entities: list[CodeEntity],
    evidence: list[EvidenceRef],
) -> None:
    parent_id = repository_id
    current: list[str] = []
    for part in PurePosixPath(path).parts[:-1]:
        current.append(part)
        directory = "/".join(current)
        if directory not in directory_ids:
            entity = _code_entity(repo_id, "directory", directory, part, directory.replace("/", "."), "", parent_id=parent_id)
            item = _code_evidence(entity, directory, None, None)
            entity.evidence_refs.append(item.id)
            directory_ids[directory] = entity.id
            entities.append(entity)
            evidence.append(item)
        parent_id = directory_ids[directory]


def _code_entity(
    repo_id: str,
    entity_type: str,
    path: str,
    name: str,
    qualified_name: str,
    source: str,
    *,
    parent_id: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    signature: str | None = None,
    docstring: str | None = None,
    declaration_ordinal: int | None = None,
    metadata: dict | None = None,
    module_name: str | None = None,
    entity_id: str | None = None,
) -> CodeEntity:
    return CodeEntity(
        id=entity_id or code_entity_id(repo_id, entity_type, path, qualified_name, declaration_ordinal),
        repo_id=repo_id,
        entity_type=entity_type,
        path=path,
        name=name,
        qualified_name=qualified_name,
        module_name=module_name or (qualified_name if entity_type in FILE_ROLE_ENTITY_TYPES.values() or entity_type == "file" else None),
        parent_id=parent_id,
        start_line=start_line,
        end_line=end_line,
        signature=signature,
        source_code=source or None,
        docstring=docstring,
        content_hash=text_content_hash(source),
        metadata=metadata or {},
    )


def _code_evidence(entity: CodeEntity, path: str, start: int | None, end: int | None) -> EvidenceRef:
    locator = f"{path}:{start or ''}:{end or ''}:{entity.id}"
    return EvidenceRef(
        id=evidence_id("code", locator, entity.content_hash),
        source_type="code",
        entity_id=entity.id,
        file_path=path,
        start_line=start,
        end_line=end,
        content_hash=entity.content_hash,
    )


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


def _docstring(source: str) -> str | None:
    if not source:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    first = tree.body[0] if tree.body else None
    return ast.get_docstring(first) if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None


def _source_range(source: str, start_line: int | None, end_line: int | None) -> str:
    if not source or start_line is None or end_line is None or start_line < 1 or end_line < start_line:
        return ""
    return "\n".join(source.splitlines()[start_line - 1:end_line])


def _unconditional_declarations(source: str) -> set[tuple[str, str | None, str, int]]:
    result: set[tuple[str, str | None, str, int]] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return result
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            result.add(("class", None, node.name, node.lineno))
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result.add(("method", node.name, member.name, member.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.add(("function", None, node.name, node.lineno))
    return result


def _method_parent(candidates: list[tuple[int, int, str]], line: int | None) -> str | None:
    if line is None:
        return candidates[-1][2] if candidates else None
    containing = [item for item in candidates if item[0] <= line <= item[1]]
    return max(containing, default=None, key=lambda item: item[0])[2] if containing else None


def _dedupe_entities(items: list[CodeEntity]) -> list[CodeEntity]:
    return list({item.id: item for item in items}.values())


def _dedupe_evidence(items: list[EvidenceRef]) -> list[EvidenceRef]:
    return list({item.id: item for item in items}.values())
