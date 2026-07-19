from __future__ import annotations

import pytest

from backend.app.config.application import ApplicationConfig, ArtifactSettings, ComputeSettings
from backend.app.control_plane.cli import build_parser
from backend.app.control_plane.config import DeploymentProfile, PlatformSettings
from backend.app.control_plane.doctor import doctor_ok, run_doctor


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
    args = parser.parse_args(["serve", "--config", "config/local-cpu.yaml"])
    assert args.config == "config/local-cpu.yaml"


def test_local_doctor_warns_for_missing_model_cache(tmp_path):
    manifest = tmp_path / "models.yaml"
    manifest.write_text("models: []\n", encoding="utf-8")
    config = ApplicationConfig(
        model_manifest=manifest,
        artifacts=ArtifactSettings(local_root=tmp_path / "artifacts"),
        compute=ComputeSettings(model_cache=tmp_path / "models"),
    )

    checks = run_doctor(config)

    model_cache = next(check for check in checks if check.name == "model_cache")
    assert model_cache.status == "warning"
    assert doctor_ok(checks)
