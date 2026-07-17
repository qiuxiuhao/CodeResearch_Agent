from __future__ import annotations

from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.index_manifest import SymbolChunk
from backend.app.indexing.stable_ids import symbol_chunk_id, text_content_hash


CHUNK_TYPES = {
    "function": "function",
    "method": "method",
    "class": "class",
    "file": "file",
    "config": "file",
    "training_entry": "file",
    "inference_entry": "file",
    "dataset": "file",
    "model_module": "model_module",
}


def build_symbol_chunks(
    repo_id: str,
    code_entities: list[CodeEntity],
    paper_entities: list[PaperEntity],
) -> list[SymbolChunk]:
    chunks: list[SymbolChunk] = []
    for entity in code_entities:
        chunk_type = CHUNK_TYPES.get(entity.entity_type)
        if not chunk_type:
            continue
        text = entity.source_code or _code_fallback(entity)
        if not text:
            continue
        digest = text_content_hash(text)
        chunks.append(SymbolChunk(
            id=symbol_chunk_id(entity.id, chunk_type, 0, digest),
            repo_id=entity.repo_id,
            entity_id=entity.id,
            entity_kind="code",
            chunk_type=chunk_type,
            path=entity.path,
            start_line=entity.start_line,
            end_line=entity.end_line,
            text=text,
            content_hash=digest,
            char_count=len(text),
        ))
    for entity in paper_entities:
        if not entity.text:
            continue
        digest = text_content_hash(entity.text)
        chunks.append(SymbolChunk(
            id=symbol_chunk_id(entity.id, "paper_entity", 0, digest),
            repo_id=repo_id,
            entity_id=entity.id,
            entity_kind="paper",
            chunk_type="paper_entity",
            page_number=entity.page_number,
            text=entity.text,
            content_hash=digest,
            char_count=len(entity.text),
        ))
    return chunks


def _code_fallback(entity: CodeEntity) -> str:
    details = [entity.qualified_name]
    if entity.signature:
        details.append(entity.signature)
    if entity.docstring:
        details.append(entity.docstring)
    return "\n".join(item for item in details if item)
