from __future__ import annotations

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
        await self.app(scope, receive, send)
