from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any

from backend.app.observability.schemas import JsonValue


_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|password|passwd|secret|cookie|token|connection[_-]?string)"
)
_SAFE_ERROR_TEMPLATES = {
    "operation_failed",
    "operation_timed_out",
    "operation_cancelled",
    "store_unavailable",
    "validation_failed",
    "provider_unavailable",
    "telemetry_command_conflict",
}


@dataclass(frozen=True, slots=True)
class HMACHasher:
    key_id: str | None
    key: bytes | None
    algorithm: str = "HMAC-SHA256"

    def digest(self, value: str) -> str | None:
        if not self.key or not self.key_id:
            return None
        return hmac.new(self.key, value.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class Redactor:
    hasher: HMACHasher

    def redact_attributes(self, attributes: dict[str, Any]) -> dict[str, JsonValue]:
        output: dict[str, JsonValue] = {}
        for key, value in attributes.items():
            if _SECRET_PATTERN.search(key):
                continue
            if isinstance(value, str) and _SECRET_PATTERN.search(value):
                continue
            output[key] = value
        return output

    def safe_error(
        self, exc: BaseException, *, error_code: str | None = None
    ) -> tuple[str, str, str | None]:
        template = _template_for_error(error_code)
        return type(exc).__name__[:256], template, self.hasher.digest(str(exc))


def _template_for_error(error_code: str | None) -> str:
    if error_code and "timeout" in error_code:
        return "operation_timed_out"
    if error_code and "cancel" in error_code:
        return "operation_cancelled"
    if error_code and ("store" in error_code or "database" in error_code):
        return "store_unavailable"
    if error_code and "validation" in error_code:
        return "validation_failed"
    return "operation_failed"


def validate_error_template(template: str) -> str:
    if template not in _SAFE_ERROR_TEMPLATES:
        raise ValueError("error template is not registered")
    return template
