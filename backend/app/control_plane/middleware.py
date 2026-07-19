from __future__ import annotations

import re
import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import DeploymentProfile, PlatformSettings


class TeamLegacyApiGuardMiddleware:
    """Team profile exposes only versioned v2 API; it never falls back to legacy Local routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            settings = PlatformSettings.from_env()
            path = str(scope.get("path") or "")
            if settings.profile is DeploymentProfile.TEAM and not (
                path.startswith("/api/v2") or path in {"/health", "/docs", "/openapi.json"}
            ):
                response = JSONResponse(
                    {"detail": {"error_code": "legacy_api_disabled_in_team_profile"}},
                    status_code=404,
                )
                await response(scope, receive, send)
                return
            if (
                settings.profile is DeploymentProfile.LOCAL
                and bool(os.getenv("CRA_CONFIG_PATH"))
                and str(scope.get("method") or "").upper() in {"POST", "PUT", "DELETE"}
                and _is_legacy_scheduling_path(path)
            ):
                response = JSONResponse(
                    {"detail": {"error_code": "legacy_scheduling_api_disabled"}},
                    status_code=410,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


_LEGACY_SCHEDULING_PATTERNS = (
    re.compile(r"^/analysis/tasks(?:/async|/upload(?:/async)?)?$"),
    re.compile(r"^/repositories/[^/]+/research/agent/runs$"),
    re.compile(r"^/research/agent/runs/[^/]+/(?:resume|cancel)$"),
    re.compile(r"^/repositories/[^/]+/alignments/runs$"),
    re.compile(r"^/alignments/runs/[^/]+/cancel$"),
    re.compile(r"^/evaluations/runs$"),
    re.compile(r"^/evaluations/runs/[^/]+/cancel$"),
)


def _is_legacy_scheduling_path(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in _LEGACY_SCHEDULING_PATTERNS)


def mark_legacy_scheduling_routes_deprecated(app) -> None:
    """Keep internal handlers importable while excluding them from new client generation."""
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        if _is_legacy_scheduling_path(path) and methods.intersection({"POST", "PUT", "DELETE"}):
            route.deprecated = True
