from __future__ import annotations

import json
from typing import Any


def parse_json_object(content: Any, *, allow_embedded: bool = False) -> dict:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("response content is not text")
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = "\n".join(stripped.splitlines()[1:-1]).strip()
    if allow_embedded:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("response does not contain a JSON object")
        stripped = stripped[start : end + 1]
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("structured result is not an object")
    return value


def optional_usage_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None
