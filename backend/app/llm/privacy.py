from __future__ import annotations

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
