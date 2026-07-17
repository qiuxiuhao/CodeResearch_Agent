from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from backend.app.config.pdf_safety import PDFSafetySettings
from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import IndexManifest, IndexedFile, SymbolChunk
from backend.app.indexing.call_graph_builder import build_call_edges, build_structure_edges
from backend.app.indexing.code_chunker import build_symbol_chunks
from backend.app.indexing.code_entity_builder import build_code_entities
from backend.app.indexing.import_resolver import resolve_imports
from backend.app.indexing.inheritance_resolver import build_inheritance_edges
from backend.app.indexing.input_fingerprint import (
    BUILDER_VERSIONS,
    INDEX_SCHEMA_VERSION,
    build_input_payload,
    input_hash,
)
from backend.app.indexing.module_roots import discover_module_roots
from backend.app.indexing.paper_entity_builder import build_paper_entities
from backend.app.indexing.path_normalizer import normalize_index_path
from backend.app.indexing.stable_ids import (
    bytes_content_hash,
    code_entity_id,
    evidence_id,
    knowledge_edge_id,
    repository_identity,
    text_content_hash,
)
from backend.app.indexing.symbol_table_builder import build_symbol_table
from backend.app.persistence.index_store import IndexArtifacts, StructuredIndexStore
from backend.app.utils.file_utils import DEFAULT_MAX_FILE_SIZE_BYTES
from backend.app.utils.path_utils import SKIP_DIR_NAMES


MANIFEST_VERSION = "1.4.0"
DEFAULT_INDEX_DB_PATH = "data/structured_index.sqlite3"


def build_structured_index(
    state: dict[str, Any],
    *,
    repository_key: str | None = None,
    index_db_path: str | Path | None = None,
) -> IndexManifest:
    task_id = str(state.get("task_id") or "")
    repo_path = Path(str(state.get("repo_path") or ""))
    output_dir = Path(str(state.get("output_dir") or ""))
    if not task_id or not repo_path.is_dir() or not output_dir:
        raise ValueError("Structured index requires task_id, repo_path, and output_dir.")

    repo_id, identity_mode, normalized_key = repository_identity(task_id, repository_key)
    module_roots = discover_module_roots(repo_path)
    file_snapshots = _collect_file_snapshots(state, repo_path)
    paper_digest = _paper_digest(state.get("paper_pdf_path"))
    pdf_settings = PDFSafetySettings.from_env()
    effective_options = {
        "module_roots": module_roots,
        "indexed_extensions": sorted({PurePosixPath(item["path"]).suffix for item in file_snapshots}),
        "ignored_directories": sorted(SKIP_DIR_NAMES),
        "max_file_bytes": DEFAULT_MAX_FILE_SIZE_BYTES,
        "paper_max_pages": pdf_settings.max_pages,
        "paper_max_text_chars": pdf_settings.max_text_chars,
        "chunk_policy_version": "symbol-v1",
        "unresolved_policy_version": "retain-v1",
    }
    payload = build_input_payload(
        repo_id=repo_id,
        repository_identity_mode=identity_mode,
        files=[{key: item[key] for key in ("path", "kind", "size_bytes", "content_hash")} for item in file_snapshots],
        paper_content_hash=paper_digest,
        effective_options=effective_options,
    )
    fingerprint = input_hash(payload)
    store = StructuredIndexStore(index_db_path or os.getenv("STRUCTURED_INDEX_DB_PATH") or DEFAULT_INDEX_DB_PATH)
    lease = store.begin_version(
        repo_id=repo_id,
        identity_mode=identity_mode,
        repository_key=normalized_key,
        display_name=repo_path.name,
        input_hash=fingerprint,
    )
    if lease.reused:
        manifest = _manifest_from_store(store, lease.index_version_id, repo_id, identity_mode, fingerprint, "reused")
        _write_manifest(output_dir / "index_manifest.json", manifest)
        return manifest

    staging_path = output_dir / ".index_staging" / f"{lease.index_version_id}.jsonl"
    try:
        artifacts = _build_artifacts(
            state=state,
            repo_id=repo_id,
            repo_path=repo_path,
            module_roots=module_roots,
            file_snapshots=file_snapshots,
            paper_digest=paper_digest,
        )
        _write_staging(staging_path, artifacts)
        store.mark_ready(lease)
        activated_at = store.activate(lease, artifacts)
        manifest = _manifest_from_artifacts(
            artifacts, lease.index_version_id, lease.sequence, repo_id, identity_mode,
            fingerprint, "active", activated_at,
        )
        _write_manifest(output_dir / "index_manifest.json", manifest)
        staging_path.unlink(missing_ok=True)
        return manifest
    except Exception as exc:
        store.mark_failed(lease, {
            "error_code": "structured_index_build_failed",
            "component": "index_service",
            "message": str(exc),
            "retryable": False,
        })
        raise


def _build_artifacts(
    *,
    state: dict[str, Any],
    repo_id: str,
    repo_path: Path,
    module_roots: list[str],
    file_snapshots: list[dict[str, Any]],
    paper_digest: str | None,
) -> IndexArtifacts:
    code_entities, code_evidence = build_code_entities(
        repo_id=repo_id,
        repo_path=repo_path,
        parsed_files=state.get("parsed_files", []),
        file_analysis=state.get("file_analysis", []),
        model_analysis=state.get("model_analysis", []),
        module_roots=module_roots,
    )
    config_entities, config_evidence = _build_config_entities(repo_id, code_entities, repo_path, file_snapshots)
    code_entities.extend(config_entities)
    paper_id, paper_entities, paper_evidence = build_paper_entities(
        state.get("paper_analysis", {}), state.get("paper_figure_analysis", {}), paper_digest
    )
    table = build_symbol_table(code_entities)
    import_bindings, import_edges, import_evidence = resolve_imports(
        repo_id=repo_id,
        parsed_files=state.get("parsed_files", []),
        table=table,
        module_roots=module_roots,
    )
    inheritance_edges, inheritance_evidence = build_inheritance_edges(repo_id, table, import_bindings)
    call_edges, call_evidence = build_call_edges(
        repo_id=repo_id,
        functions=state.get("functions", []),
        table=table,
        import_bindings=import_bindings,
        module_roots=module_roots,
    )
    alignment_edges, alignment_evidence = _alignment_edges(
        repo_id, paper_id, paper_entities, code_entities, state.get("paper_code_alignment", {})
    )
    edges = _merge_edges([
        *build_structure_edges(repo_id, table),
        *import_edges,
        *inheritance_edges,
        *call_edges,
        *alignment_edges,
    ])
    evidence = _dedupe_evidence([
        *code_evidence, *config_evidence, *paper_evidence, *import_evidence,
        *inheritance_evidence, *call_evidence, *alignment_evidence,
    ])
    chunks = build_symbol_chunks(repo_id, code_entities, paper_entities)
    indexed_files = _indexed_files(file_snapshots, state.get("parsed_files", []), code_entities, edges, evidence, chunks)
    return IndexArtifacts(indexed_files, code_entities, paper_entities, edges, evidence, chunks)


def _collect_file_snapshots(state: dict[str, Any], repo_path: Path) -> list[dict[str, Any]]:
    repo_index = state.get("repo_index", {})
    python_files = list(repo_index.get("python_files", state.get("python_files", [])))
    config_files = list(repo_index.get("config_file_candidates", []))
    kinds = {path: "python" for path in python_files}
    kinds.update({path: "config" for path in config_files})
    snapshots: list[dict[str, Any]] = []
    for raw_path, kind in sorted(kinds.items()):
        path = normalize_index_path(raw_path)
        physical = repo_path / path
        try:
            data = physical.read_bytes()
            size = len(data)
            try:
                digest = text_content_hash(data.decode("utf-8-sig"))
            except UnicodeDecodeError:
                digest = bytes_content_hash(data)
            parse_status = "success" if size <= DEFAULT_MAX_FILE_SIZE_BYTES else "skipped"
            errors = [] if parse_status == "success" else [{"error_code": "file_too_large"}]
        except OSError as exc:
            size = 0
            digest = bytes_content_hash(b"")
            parse_status = "failed"
            errors = [{"error_code": type(exc).__name__, "message": str(exc)}]
        snapshots.append({
            "path": path,
            "kind": kind,
            "size_bytes": size,
            "content_hash": digest,
            "parse_status": parse_status,
            "errors": errors,
        })
    return snapshots


def _build_config_entities(
    repo_id: str,
    existing: list[CodeEntity],
    repo_path: Path,
    snapshots: list[dict[str, Any]],
) -> tuple[list[CodeEntity], list[EvidenceRef]]:
    existing_paths = {item.path for item in existing}
    repository = next((item for item in existing if item.entity_type == "repository"), None)
    entities: list[CodeEntity] = []
    evidence: list[EvidenceRef] = []
    for snapshot in snapshots:
        if snapshot["kind"] != "config" or snapshot["path"] in existing_paths:
            continue
        path = snapshot["path"]
        try:
            source = (repo_path / path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            source = ""
        entity = CodeEntity(
            id=code_entity_id(repo_id, "config", path, path),
            repo_id=repo_id,
            entity_type="config",
            path=path,
            name=PurePosixPath(path).name,
            qualified_name=path,
            parent_id=repository.id if repository else None,
            source_code=source or None,
            content_hash=snapshot["content_hash"],
            metadata={"file_role": "config_related"},
        )
        ev = EvidenceRef(
            id=evidence_id("code", f"{path}:config", entity.content_hash),
            source_type="code",
            entity_id=entity.id,
            file_path=path,
            content_hash=entity.content_hash,
        )
        entity.evidence_refs.append(ev.id)
        entities.append(entity)
        evidence.append(ev)
    return entities, evidence


def _alignment_edges(
    repo_id: str,
    paper_id: str | None,
    paper_entities: list[PaperEntity],
    code_entities: list[CodeEntity],
    alignment: dict,
) -> tuple[list[KnowledgeEdge], list[EvidenceRef]]:
    if not paper_id:
        return [], []
    contributions = {
        item.metadata.get("legacy_contribution_id"): item
        for item in paper_entities if item.entity_type == "contribution"
    }
    edges: list[KnowledgeEdge] = []
    evidence: list[EvidenceRef] = []
    for item in alignment.get("alignment_items", []):
        source = contributions.get(item.get("contribution_id"))
        if source is None:
            continue
        for target_data in item.get("matched_targets", []):
            target = _find_alignment_target(code_entities, target_data)
            if target is None:
                continue
            locator = f"{source.id}:{target.id}:alignment"
            ev = EvidenceRef(
                id=evidence_id("alignment", locator, source.content_hash),
                source_type="alignment",
                entity_id=source.id,
                paper_id=paper_id,
                page_number=source.page_number,
                content_hash=source.content_hash,
            )
            edges.append(KnowledgeEdge(
                id=knowledge_edge_id(source.id, "ALIGNS_WITH", target.id),
                repo_id=repo_id,
                source_id=source.id,
                target_id=target.id,
                edge_type="ALIGNS_WITH",
                confidence={"high": 0.9, "medium": 0.65, "low": 0.35}.get(item.get("confidence"), 0.35),
                resolution_type="exact",
                evidence_refs=[ev.id],
                metadata={"legacy_reason": item.get("reason", "")},
            ))
            evidence.append(ev)
    return edges, evidence


def _find_alignment_target(entities: list[CodeEntity], target: dict) -> CodeEntity | None:
    path = target.get("file_path")
    qualified = target.get("qualified_name")
    name = target.get("name")
    candidates = [item for item in entities if not path or item.path == path]
    if qualified:
        exact = [item for item in candidates if item.qualified_name == qualified or item.qualified_name.endswith(f".{qualified}")]
        if len(exact) == 1:
            return exact[0]
    named = [item for item in candidates if item.name == name or item.qualified_name == name]
    return named[0] if len(named) == 1 else None


def _indexed_files(
    snapshots: list[dict[str, Any]],
    parsed_files: list[dict],
    entities: list[CodeEntity],
    edges: list[KnowledgeEdge],
    evidence: list[EvidenceRef],
    chunks: list[SymbolChunk],
) -> list[IndexedFile]:
    parsed = {item.get("file_path", ""): item for item in parsed_files}
    entities_by_path = Counter(item.path for item in entities)
    chunks_by_path = Counter(item.path for item in chunks if item.path)
    edge_by_path: Counter[str] = Counter()
    evidence_by_id = {item.id: item for item in evidence}
    for edge in edges:
        paths = {evidence_by_id[ref].file_path for ref in edge.evidence_refs if ref in evidence_by_id}
        for path in paths:
            if path:
                edge_by_path[path] += 1
    result: list[IndexedFile] = []
    for snapshot in snapshots:
        path = snapshot["path"]
        parse_errors = parsed.get(path, {}).get("errors", [])
        status = snapshot["parse_status"]
        if parse_errors and status == "success":
            status = "failed"
        errors = [*snapshot["errors"], *parse_errors]
        result.append(IndexedFile(
            path=path,
            kind=snapshot["kind"],
            content_hash=snapshot["content_hash"],
            size_bytes=snapshot["size_bytes"],
            parse_status=status,
            entity_count=entities_by_path[path],
            edge_count=edge_by_path[path],
            chunk_count=chunks_by_path[path],
            errors=errors,
        ))
    return result


def _merge_edges(items: list[KnowledgeEdge]) -> list[KnowledgeEdge]:
    merged: dict[str, KnowledgeEdge] = {}
    for item in items:
        current = merged.get(item.id)
        if current is None:
            merged[item.id] = item
        else:
            current.evidence_refs = list(dict.fromkeys([*current.evidence_refs, *item.evidence_refs]))
    return list(merged.values())


def _dedupe_evidence(items: list[EvidenceRef]) -> list[EvidenceRef]:
    return list({item.id: item for item in items}.values())


def _write_staging(path: Path, artifacts: IndexArtifacts) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    groups = {
        "indexed_file": artifacts.indexed_files,
        "code_entity": artifacts.code_entities,
        "paper_entity": artifacts.paper_entities,
        "edge": artifacts.edges,
        "evidence": artifacts.evidence,
        "chunk": artifacts.chunks,
    }
    lines = [
        json.dumps({"kind": kind, "value": item.model_dump(mode="json")}, ensure_ascii=False, sort_keys=True)
        for kind, values in groups.items() for item in values
    ]
    temp = path.with_suffix(".tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(path)


def _write_manifest(path: Path, manifest: IndexManifest) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _manifest_from_artifacts(
    artifacts: IndexArtifacts,
    version_id: str,
    sequence: int,
    repo_id: str,
    identity_mode: str,
    fingerprint: str,
    status: str,
    activated_at: str | None,
) -> IndexManifest:
    resolutions = Counter(item.resolution_type for item in artifacts.edges)
    return IndexManifest(
        manifest_version=MANIFEST_VERSION,
        index_schema_version=INDEX_SCHEMA_VERSION,
        repo_id=repo_id,
        repository_identity_mode=identity_mode,
        index_version_id=version_id,
        index_sequence=sequence,
        input_hash=fingerprint,
        status=status,
        builder_versions=BUILDER_VERSIONS,
        file_count=len(artifacts.indexed_files),
        code_entity_count=len(artifacts.code_entities),
        paper_entity_count=len(artifacts.paper_entities),
        edge_count=len(artifacts.edges),
        evidence_count=len(artifacts.evidence),
        chunk_count=len(artifacts.chunks),
        unresolved_call_count=resolutions["unresolved"],
        ambiguous_call_count=resolutions["ambiguous"],
        created_at=datetime.now(UTC),
        activated_at=datetime.fromisoformat(activated_at) if activated_at else None,
    )


def _manifest_from_store(
    store: StructuredIndexStore,
    version_id: str,
    repo_id: str,
    identity_mode: str,
    fingerprint: str,
    status: str,
) -> IndexManifest:
    counts = store.version_counts(version_id)
    resolutions = store.resolution_counts(version_id)
    row = store.version_row(version_id) or {}
    return IndexManifest(
        manifest_version=MANIFEST_VERSION,
        index_schema_version=INDEX_SCHEMA_VERSION,
        repo_id=repo_id,
        repository_identity_mode=identity_mode,
        index_version_id=version_id,
        index_sequence=int(row.get("sequence", 1)),
        input_hash=fingerprint,
        status=status,
        builder_versions=BUILDER_VERSIONS,
        unresolved_call_count=resolutions["unresolved"],
        ambiguous_call_count=resolutions["ambiguous"],
        created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(UTC),
        activated_at=datetime.fromisoformat(row["activated_at"]) if row.get("activated_at") else None,
        **counts,
    )


def _paper_digest(path_value: object) -> str | None:
    if not path_value:
        return None
    try:
        return bytes_content_hash(Path(str(path_value)).read_bytes())
    except OSError:
        return None
