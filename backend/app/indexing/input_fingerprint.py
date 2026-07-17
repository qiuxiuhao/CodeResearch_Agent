from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any


INPUT_HASH_VERSION = "1"
INDEX_SCHEMA_VERSION = "1.4.0"
PATH_NORMALIZATION_VERSION = "1"
PARSER_VERSION = "1.3.5-ast"
BUILDER_VERSIONS = {
    "code_entity": "1",
    "paper_entity": "1",
    "symbol_table": "1",
    "import_resolver": "1",
    "call_graph": "1",
    "chunker": "1",
}


def build_input_payload(
    *,
    repo_id: str,
    repository_identity_mode: str,
    files: list[dict[str, Any]],
    paper_content_hash: str | None,
    effective_options: dict[str, Any],
    index_schema_version: str = INDEX_SCHEMA_VERSION,
    builder_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized_files = sorted(
        (_normalize_json(item) for item in files),
        key=lambda item: (str(item.get("path", "")), str(item.get("kind", ""))),
    )
    options = _normalize_json(effective_options)
    for field in ("module_roots", "indexed_extensions", "ignored_directories"):
        if isinstance(options.get(field), list):
            options[field] = sorted(set(options[field]))
    return {
        "input_hash_version": INPUT_HASH_VERSION,
        "repo_id": repo_id,
        "repository_identity_mode": repository_identity_mode,
        "index_schema_version": index_schema_version,
        "path_normalization_version": PATH_NORMALIZATION_VERSION,
        "parser_version": PARSER_VERSION,
        "builder_versions": dict(sorted((builder_versions or BUILDER_VERSIONS).items())),
        "effective_options": options,
        "files": normalized_files,
        "paper": {"provided": paper_content_hash is not None, "content_hash": paper_content_hash},
    }


def input_hash(payload: dict[str, Any]) -> str:
    canonical = canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_json(payload: dict[str, Any]) -> str:
    normalized = _normalize_json(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", str(key)): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Canonical input JSON must not contain NaN or Infinity.")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")
