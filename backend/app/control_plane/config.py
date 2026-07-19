from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.config.application import ApplicationConfig


class DeploymentProfile(StrEnum):
    LOCAL = "local"
    TEAM = "team"


class PlatformSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: DeploymentProfile = DeploymentProfile.LOCAL
    control_database_url: str = "sqlite:///data/control_plane.sqlite3"
    observability_database_url: str = "sqlite:///data/observability.sqlite3"
    checkpoint_database_url: str = "sqlite:///data/research_checkpoints.sqlite3"
    artifact_root: Path = Path("data/artifacts")
    redis_url: str | None = None
    celery_broker_url: str | None = None
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    qdrant_url: str | None = None
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def validate_profile_dependencies(self) -> "PlatformSettings":
        if self.profile is DeploymentProfile.TEAM:
            required = {
                "CONTROL_DATABASE_URL": self.control_database_url.startswith(("postgresql://", "postgresql+")),
                "OBSERVABILITY_DATABASE_URL": self.observability_database_url.startswith(("postgresql://", "postgresql+")),
                "CHECKPOINT_DATABASE_URL": self.checkpoint_database_url.startswith(("postgresql://", "postgresql+")),
                "REDIS_URL": bool(self.redis_url),
                "CELERY_BROKER_URL": bool(self.celery_broker_url),
                "S3_ENDPOINT_URL": bool(self.s3_endpoint_url),
                "S3_BUCKET": bool(self.s3_bucket),
                "QDRANT_URL": bool(self.qdrant_url),
            }
            missing = [name for name, present in required.items() if not present]
            if missing:
                raise ValueError(f"team profile dependencies missing: {','.join(missing)}")
        return self

    @classmethod
    def from_env(cls) -> "PlatformSettings":
        config_path = os.getenv("CRA_CONFIG_PATH")
        if config_path:
            return cls.from_application(ApplicationConfig.load(config_path))
        profile = DeploymentProfile(os.getenv("CRA_DEPLOYMENT_PROFILE", "local").strip().lower())
        return cls(
            profile=profile,
            control_database_url=os.getenv("CONTROL_DATABASE_URL", "sqlite:///data/control_plane.sqlite3"),
            observability_database_url=os.getenv("OBSERVABILITY_DATABASE_URL", "sqlite:///data/observability.sqlite3"),
            checkpoint_database_url=os.getenv("CHECKPOINT_DATABASE_URL", "sqlite:///data/research_checkpoints.sqlite3"),
            artifact_root=Path(os.getenv("LOCAL_ARTIFACT_ROOT", "data/artifacts")),
            redis_url=os.getenv("REDIS_URL"),
            celery_broker_url=os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL"),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            s3_bucket=os.getenv("S3_BUCKET"),
            qdrant_url=os.getenv("QDRANT_URL"),
        )

    @classmethod
    def from_application(cls, config: ApplicationConfig) -> "PlatformSettings":
        return cls(
            profile=DeploymentProfile(config.profile),
            control_database_url=config.database.control_url,
            observability_database_url=config.database.observability_url,
            checkpoint_database_url=config.database.checkpoint_url,
            artifact_root=config.artifacts.local_root,
            redis_url=config.services.redis_url,
            celery_broker_url=config.services.celery_broker_url or config.services.redis_url,
            s3_endpoint_url=config.artifacts.s3_endpoint_url,
            s3_bucket=config.artifacts.s3_bucket,
            qdrant_url=config.services.qdrant_url,
            access_token_minutes=config.security.access_token_minutes,
            refresh_token_days=config.security.refresh_token_days,
        )


def sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("database URL is not SQLite")
    return Path(database_url[len(prefix):]).expanduser().resolve()
