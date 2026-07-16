from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def require_settings_write_access(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    _rate_limit(client_host or "unknown")
    if _is_local(client_host):
        _validate_origin(request, local=True)
        return
    if os.getenv("REMOTE_PROVIDER_SETTINGS_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=403, detail="Provider settings writes are local-only by default.")
    token = os.getenv("PROVIDER_SETTINGS_ADMIN_TOKEN", "")
    provided = request.headers.get("x-admin-token", "")
    if not token or not hmac.compare_digest(token, provided):
        raise HTTPException(status_code=403, detail="Admin token is required for remote provider settings writes.")
    _validate_origin(request, local=False)


def _is_local(host: str) -> bool:
    return host in LOCAL_HOSTS


def _validate_origin(request: Request, *, local: bool) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = {
        parsed
        for item in os.getenv(
            "PROVIDER_SETTINGS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if (parsed := _parse_origin(item.strip())) is not None
    }
    parsed_origin = _parse_origin(origin)
    if parsed_origin is None or parsed_origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin is not allowed for provider settings writes.")


def _parse_origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    return (parsed.scheme.lower(), parsed.hostname.lower(), port)


def _rate_limit(key: str) -> None:
    limit = int(os.getenv("PROVIDER_SETTINGS_RATE_LIMIT_PER_MINUTE", "60"))
    now = time.monotonic()
    bucket = _RATE_BUCKETS[key]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Provider settings rate limit exceeded.")
    bucket.append(now)
