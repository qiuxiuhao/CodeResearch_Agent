from __future__ import annotations

import os
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import DeploymentProfile, PlatformSettings


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


class LegacyApiGuardMiddleware:
    """Expose v2 as the only public business API while legacy handlers stay importable."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            settings = PlatformSettings.from_env()
            path = str(scope.get("path") or "")
            method = str(scope.get("method") or "").upper()
            if _is_legacy_business_path(path) and not _legacy_internal_api_enabled(settings, scope):
                status = 404 if settings.profile is DeploymentProfile.TEAM else 410
                response = JSONResponse(
                    {"detail": {"error_code": "legacy_api_disabled"}},
                    status_code=status,
                )
                await response(scope, receive, send)
                return
            if (
                settings.profile is DeploymentProfile.LOCAL
                and bool(os.getenv("CRA_CONFIG_PATH"))
                and method in {"POST", "PUT", "DELETE"}
                and _is_legacy_scheduling_path(path)
            ):
                response = JSONResponse(
                    {"detail": {"error_code": "legacy_scheduling_api_disabled"}},
                    status_code=410,
                )
                await response(scope, receive, send)
                return
            if path in {"/docs", "/redoc", "/openapi.json"} and not _request_is_local(scope):
                response = JSONResponse(
                    {"detail": {"error_code": "developer_docs_local_only"}},
                    status_code=404,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


TeamLegacyApiGuardMiddleware = LegacyApiGuardMiddleware


_LEGACY_BUSINESS_PREFIXES = (
    "/analysis",
    "/repositories",
    "/research",
    "/alignments",
    "/evaluations",
    "/evaluation",
    "/bad-cases",
    "/observability",
    "/settings",
    "/library",
    "/llm",
    "/vision",
    "/image-generation",
)


_LEGACY_SCHEDULING_PATTERNS = (
    re.compile(r"^/analysis/tasks(?:/async|/upload(?:/async)?)?$"),
    re.compile(r"^/repositories/[^/]+/research/agent/runs$"),
    re.compile(r"^/research/agent/runs/[^/]+/(?:resume|cancel)$"),
    re.compile(r"^/repositories/[^/]+/alignments/runs$"),
    re.compile(r"^/alignments/runs/[^/]+/cancel$"),
    re.compile(r"^/evaluations/runs$"),
    re.compile(r"^/evaluations/runs/[^/]+/cancel$"),
)


def _is_legacy_business_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _LEGACY_BUSINESS_PREFIXES)


def _is_legacy_scheduling_path(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in _LEGACY_SCHEDULING_PATTERNS)


def mark_legacy_routes_internal(app) -> None:
    """Keep legacy handlers importable while excluding them from the public OpenAPI contract."""
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        if _is_legacy_business_path(path):
            route.include_in_schema = False
            route.deprecated = True


def mark_legacy_scheduling_routes_deprecated(app) -> None:
    mark_legacy_routes_internal(app)


def _request_is_local(scope: Scope) -> bool:
    client = scope.get("client")
    if not client:
        return False
    host = str(client[0])
    return host in LOCAL_HOSTS


def _legacy_internal_api_enabled(settings: PlatformSettings, scope: Scope) -> bool:
    if settings.profile is not DeploymentProfile.LOCAL or not _request_is_local(scope):
        return False
    return os.getenv("CRA_LEGACY_INTERNAL_API_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
