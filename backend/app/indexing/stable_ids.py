from __future__ import annotations

import hashlib
import unicodedata

from backend.app.indexing.path_normalizer import normalize_index_path


def repository_identity(task_id: str, repository_key: str | None = None) -> tuple[str, str, str | None]:
    if repository_key is not None:
        normalized_key = unicodedata.normalize("NFC", repository_key.strip())
        if not normalized_key:
            raise ValueError("repository_key must not be empty.")
        return _identifier("repo", f"repo:v1\0explicit\0{normalized_key}"), "explicit", normalized_key
    if not task_id:
        raise ValueError("task_id is required for task-scoped repository identity.")
    return _identifier("repo", f"repo:v1\0task\0{task_id}"), "task_scoped", None


def code_entity_id(
    repo_id: str,
    entity_type: str,
    path: str,
    qualified_name: str = "",
    declaration_ordinal: int | None = None,
) -> str:
    normalized_path = "." if path == "." else normalize_index_path(path)
    key = f"{repo_id}\0{entity_type}\0{normalized_path}\0{qualified_name}"
    if declaration_ordinal is not None:
        key += f"\0#decl:{declaration_ordinal}"
    return _identifier("ent", key)


def paper_entity_id(paper_id: str, entity_type: str, locator: str, ordinal: int = 0) -> str:
    return _identifier("pent", f"{paper_id}\0{entity_type}\0{locator}\0{ordinal}")


def model_module_entity_id(repo_id: str, parent_class_entity_id: str, member_name: str) -> str:
    normalized_member = unicodedata.normalize("NFC", member_name)
    return _identifier("ent", f"{repo_id}\0model_module\0{parent_class_entity_id}\0{normalized_member}")


def knowledge_edge_id(source_id: str, edge_type: str, target_or_symbol: str) -> str:
    return _identifier("edge", f"{source_id}\0{edge_type}\0{target_or_symbol}")


def evidence_id(source_type: str, locator: str, content_digest: str | None = None) -> str:
    return _identifier("ev", f"{source_type}\0{locator}\0{content_digest or ''}")


def symbol_chunk_id(entity_id: str, chunk_type: str, ordinal: int, content_digest: str) -> str:
    return _identifier("chunk", f"{entity_id}\0{chunk_type}\0{ordinal}\0{content_digest}")


def normalized_text(value: str) -> str:
    if value.startswith("\ufeff"):
        value = value[1:]
    return value.replace("\r\n", "\n").replace("\r", "\n")


def text_content_hash(value: str) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def bytes_content_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def paper_id_from_hash(content_digest: str) -> str:
    return _identifier("paper", content_digest)


def _identifier(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
