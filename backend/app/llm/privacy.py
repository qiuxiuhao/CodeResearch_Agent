from __future__ import annotations

import copy
import json
import re
from typing import Any


SENSITIVE_FILE_PATTERNS = (
    re.compile(r"(^|/)\.env(?:\.|$)", re.I),
    re.compile(r"\.(?:pem|key)$", re.I),
    re.compile(r"(^|/)(?:credentials?|secrets?)(?:\.|/|$)", re.I),
)

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.I | re.S),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*(['\"]?)[^\s,'\";]+\2"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s'\"]+"),
)


def is_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in SENSITIVE_FILE_PATTERNS)


def redact_text(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern in SECRET_PATTERNS:
        redacted, replacements = pattern.subn("[REDACTED_SECRET]", redacted)
        count += replacements
    return redacted, count


def sanitize_payload(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        total = 0
        items = []
        for item in value:
            sanitized, count = sanitize_payload(item)
            items.append(sanitized)
            total += count
        return items, total
    if isinstance(value, dict):
        total = 0
        result = {}
        for key, item in value.items():
            if key in {"file_path", "path"} and isinstance(item, str) and is_sensitive_path(item):
                total += 1
                continue
            sanitized, count = sanitize_payload(item)
            result[key] = sanitized
            total += count
        return result, total
    return value, 0


TRUNCATION_MARKER = "...[TRUNCATED]"
IDENTITY_KEYS = {"file_path", "qualified_name", "class_name", "contribution_id"}
PRIORITY_TEXT_KEYS = {
    "source", "source_code", "docstring", "paper_text", "paper_content", "raw_text", "full_text", "body_text",
    "abstract", "description",
}
PRIORITY_LIST_KEYS = {
    "model_context", "imports", "classes", "functions", "layers", "forward_steps", "targets",
    "implementation_logic", "computation_logic", "library_calls", "called_internal_functions",
}


def truncate_payload(value: dict[str, Any], max_chars: int) -> tuple[dict[str, Any], bool]:
    """Reduce bulky fields while preserving the payload's structured identity and evidence."""
    payload = copy.deepcopy(value)
    if _serialized_size(payload) <= max_chars:
        return payload, False

    _shrink_matching_strings(payload, max_chars, PRIORITY_TEXT_KEYS, minimum=0)
    _shrink_matching_lists(payload, max_chars, PRIORITY_LIST_KEYS)
    _shrink_matching_lists(payload, max_chars, None)
    _shrink_matching_strings(payload, max_chars, None, minimum=48)
    return payload, True


def _serialized_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _walk(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, item in value.items():
            current_path = (*path, str(key))
            yield value, key, item, current_path
            yield from _walk(item, current_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            current_path = (*path, str(index))
            yield value, index, item, current_path
            yield from _walk(item, current_path)


def _protected(path: tuple[str, ...]) -> bool:
    return "evidence_catalog" in path or (path and path[-1] in {*IDENTITY_KEYS, "instruction"})


def _shrink_matching_strings(
    payload: dict[str, Any], max_chars: int, keys: set[str] | None, *, minimum: int
) -> None:
    candidates = [
        (parent, key, item, path)
        for parent, key, item, path in _walk(payload)
        if isinstance(item, str)
        and not _protected(path)
        and (keys is None or (path and path[-1] in keys))
    ]
    candidates.sort(key=lambda candidate: len(candidate[2]), reverse=True)
    for parent, key, text, _path in candidates:
        current_size = _serialized_size(payload)
        if current_size <= max_chars:
            return
        if len(text) <= minimum + len(TRUNCATION_MARKER):
            continue
        excess = current_size - max_chars
        keep = max(minimum, len(text) - excess - len(TRUNCATION_MARKER) - 8)
        if keep >= len(text):
            continue
        parent[key] = f"{text[:keep]}{TRUNCATION_MARKER}"


def _shrink_matching_lists(payload: dict[str, Any], max_chars: int, keys: set[str] | None) -> None:
    candidates = [
        (parent, key, item, path)
        for parent, key, item, path in _walk(payload)
        if isinstance(item, list)
        and "evidence_catalog" not in path
        and (keys is None or (path and path[-1] in keys))
    ]
    candidates.sort(key=lambda candidate: _serialized_size(candidate[2]), reverse=True)
    for parent, key, items, _path in candidates:
        if _serialized_size(payload) <= max_chars:
            return
        if len(items) <= 1:
            continue
        kept = max(1, min(8, len(items) // 2))
        omitted = len(items) - kept
        parent[key] = [*items[:kept], f"[TRUNCATED_ITEMS:{omitted}]"]
