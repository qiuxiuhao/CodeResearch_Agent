from __future__ import annotations

import pytest

from backend.app.control_plane.cli import build_parser
from backend.app.control_plane.config import DeploymentProfile, PlatformSettings


def test_local_profile_has_no_redis_or_celery_requirement():
    settings = PlatformSettings(profile=DeploymentProfile.LOCAL)
    assert settings.redis_url is None
    assert settings.celery_broker_url is None


def test_team_profile_never_falls_back_when_dependency_configuration_is_missing():
    with pytest.raises(ValueError, match="team profile dependencies missing"):
        PlatformSettings(profile=DeploymentProfile.TEAM)


def test_cra_serve_requires_explicit_profile():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["serve"])
    args = parser.parse_args(["serve", "--profile", "local"])
    assert args.profile == "local"
