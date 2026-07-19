from __future__ import annotations

import os
import platform
import warnings
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComputeSettings(StrictConfig):
    device: Literal["cpu", "cuda"] = "cpu"
    execution_providers: list[str] = Field(default_factory=lambda: ["CPUExecutionProvider"])
    batch_size: int = Field(default=32, ge=1, le=1024)
    threads: int = Field(default=0, ge=0, le=256)
    model_cache: Path = Path("data/models")
    inference_socket: Path | None = None

    @model_validator(mode="after")
    def validate_provider(self) -> "ComputeSettings":
        if self.device == "cuda":
            if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
                raise ValueError("CUDA is supported only on Linux x86_64")
            if not self.execution_providers or self.execution_providers[0] != "CUDAExecutionProvider":
                raise ValueError("CUDAExecutionProvider must be the first provider in CUDA mode")
        elif "CUDAExecutionProvider" in self.execution_providers:
            raise ValueError("CPU mode cannot request CUDAExecutionProvider")
        return self


class DatabaseSettings(StrictConfig):
    control_url: str = "sqlite:///data/control_plane.sqlite3"
    observability_url: str = "sqlite:///data/observability.sqlite3"
    checkpoint_url: str = "sqlite:///data/research_checkpoints.sqlite3"


class ArtifactSettings(StrictConfig):
    local_root: Path = Path("data/artifacts")
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None


class ServiceSettings(StrictConfig):
    redis_url: str | None = None
    celery_broker_url: str | None = None
    qdrant_url: str | None = None


class ResourceSettings(StrictConfig):
    minimum_team_cpu_cores: int = Field(default=8, ge=1)
    minimum_team_memory_gib: int = Field(default=32, ge=1)
    minimum_team_disk_gib: int = Field(default=100, ge=1)
    constrained_memory_gib: int = Field(default=48, ge=1)


class FeatureSettings(StrictConfig):
    structured_index: bool = True
    retrieval: bool = True
    dense_retrieval: bool = True
    sparse_vectors: bool = True
    reranker: bool = True
    research_agent: bool = True
    alignment: bool = True
    observability: bool = True
    observability_api: bool = True
    evaluation: bool = True
    evaluation_api: bool = True
    evaluation_live: bool = False


class SecuritySettings(StrictConfig):
    secret_backend: Literal["keyring", "encrypted_file"] = "keyring"
    secret_store_path: Path = Path("~/.coderesearch_agent/secrets.json").expanduser()
    secret_key_path: Path | None = None
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_days: int = Field(default=30, ge=1, le=365)
    secure_cookies: bool = False

    @model_validator(mode="after")
    def encrypted_file_requires_key(self) -> "SecuritySettings":
        if self.secret_backend == "encrypted_file" and self.secret_key_path is None:
            raise ValueError("encrypted_file secret backend requires secret_key_path")
        return self


class ApplicationConfig(StrictConfig):
    schema_version: Literal["2.0"] = "2.0"
    profile: Literal["local", "team"] = "local"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    artifacts: ArtifactSettings = Field(default_factory=ArtifactSettings)
    services: ServiceSettings = Field(default_factory=ServiceSettings)
    compute: ComputeSettings = Field(default_factory=ComputeSettings)
    resources: ResourceSettings = Field(default_factory=ResourceSettings)
    features: FeatureSettings = Field(default_factory=FeatureSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    model_manifest: Path = Path("config/models.yaml")

    @model_validator(mode="after")
    def validate_team(self) -> "ApplicationConfig":
        if self.profile == "team":
            required = {
                "database.control_url": self.database.control_url.startswith("postgresql"),
                "database.observability_url": self.database.observability_url.startswith("postgresql"),
                "database.checkpoint_url": self.database.checkpoint_url.startswith("postgresql"),
                "services.redis_url": bool(self.services.redis_url),
                "services.celery_broker_url": bool(self.services.celery_broker_url),
                "services.qdrant_url": bool(self.services.qdrant_url),
                "artifacts.s3_endpoint_url": bool(self.artifacts.s3_endpoint_url),
                "artifacts.s3_bucket": bool(self.artifacts.s3_bucket),
            }
            missing = [key for key, present in required.items() if not present]
            if missing:
                raise ValueError(f"team configuration missing: {','.join(missing)}")
        return self

    @classmethod
    def load(cls, path: str | Path) -> "ApplicationConfig":
        config_path = Path(path).expanduser().resolve()
        payload = _load_yaml(config_path)
        extends = payload.pop("extends", None)
        if extends:
            parent_path = (config_path.parent / str(extends)).resolve()
            payload = _deep_merge(_load_yaml(parent_path), payload)
        config = cls.model_validate(payload)
        database = config.database.model_copy(update={
            "control_url": _resolve_database_url(config.database.control_url, config_path.parent),
            "observability_url": _resolve_database_url(
                config.database.observability_url, config_path.parent,
            ),
            "checkpoint_url": _resolve_database_url(
                config.database.checkpoint_url, config_path.parent,
            ),
        })
        return config.model_copy(update={
            "database": database,
            "model_manifest": _resolve_path(config.model_manifest, config_path.parent),
            "compute": config.compute.model_copy(update={
                "model_cache": _resolve_path(config.compute.model_cache, config_path.parent),
                "inference_socket": _resolve_path(config.compute.inference_socket, config_path.parent),
            }),
            "artifacts": config.artifacts.model_copy(update={
                "local_root": _resolve_path(config.artifacts.local_root, config_path.parent),
            }),
            "security": config.security.model_copy(update={
                "secret_store_path": _resolve_path(config.security.secret_store_path, config_path.parent),
                "secret_key_path": _resolve_path(config.security.secret_key_path, config_path.parent),
            }),
        })

    def apply_legacy_environment(self) -> "ApplicationConfig":
        """Preserve old deployments without making .env the v2 configuration source."""
        mapping = {
            "CRA_DEPLOYMENT_PROFILE": ("profile",),
            "CONTROL_DATABASE_URL": ("database", "control_url"),
            "OBSERVABILITY_DATABASE_URL": ("database", "observability_url"),
            "CHECKPOINT_DATABASE_URL": ("database", "checkpoint_url"),
            "LOCAL_ARTIFACT_ROOT": ("artifacts", "local_root"),
            "REDIS_URL": ("services", "redis_url"),
            "CELERY_BROKER_URL": ("services", "celery_broker_url"),
            "QDRANT_URL": ("services", "qdrant_url"),
        }
        data = self.model_dump()
        used: list[str] = []
        for variable, path in mapping.items():
            value = os.getenv(variable)
            if value is None:
                continue
            used.append(variable)
            cursor: dict[str, Any] = data
            for part in path[:-1]:
                cursor = cursor[part]
            cursor[path[-1]] = value
        if used:
            warnings.warn(
                f"legacy environment overrides are deprecated: {','.join(sorted(used))}",
                DeprecationWarning,
                stacklevel=2,
            )
        return ApplicationConfig.model_validate(data)

    def export_runtime_compatibility(self) -> None:
        """Populate legacy module knobs from validated YAML without reading a .env file."""
        from backend.app.retrieval.model_manager import load_manifest

        models = {item.role: item for item in load_manifest(self.model_manifest).models}
        data_root = _sqlite_data_root(self.database.control_url)
        checkpoint_path = _sqlite_path_or(
            self.database.checkpoint_url, data_root / "research_checkpoints.sqlite3",
        )
        observability_path = _sqlite_path_or(
            self.database.observability_url, data_root / "observability.sqlite3",
        )
        values = {
            "CRA_DEPLOYMENT_PROFILE": self.profile,
            "CONTROL_DATABASE_URL": self.database.control_url,
            "OBSERVABILITY_DATABASE_URL": self.database.observability_url,
            "CHECKPOINT_DATABASE_URL": self.database.checkpoint_url,
            "LOCAL_ARTIFACT_ROOT": str(self.artifacts.local_root),
            "RETRIEVAL_MODEL_CACHE_DIR": str(self.compute.model_cache),
            "LIBRARY_DB_PATH": str(data_root / "python_function_library.sqlite3"),
            "STRUCTURED_INDEX_DB_PATH": str(data_root / "structured_index.sqlite3"),
            "RETRIEVAL_FTS_DB_PATH": str(data_root / "retrieval_fts.sqlite3"),
            "RETRIEVAL_MANIFEST_ROOT": str(data_root / "retrieval" / "manifests"),
            "RESEARCH_RUN_DB_PATH": str(data_root / "research_runs.sqlite3"),
            "RESEARCH_CHECKPOINT_DB_PATH": str(checkpoint_path),
            "ALIGNMENT_DB_PATH": str(data_root / "paper_code_alignment.sqlite3"),
            "EVALUATION_DB_PATH": str(data_root / "evaluation.sqlite3"),
            "OBSERVABILITY_DB_PATH": str(observability_path),
            "LLM_CACHE_PATH": str(data_root / "llm_explanation_cache.sqlite3"),
            "VLM_CACHE_PATH": str(data_root / "vlm_figure_cache.sqlite3"),
            "IMAGE_GENERATION_CACHE_PATH": str(data_root / "image_generation_cache.sqlite3"),
            "RETRIEVAL_OFFLINE": "true",
            "RETRIEVAL_DENSE_MODEL_ID": models["dense"].model_id,
            "RETRIEVAL_DENSE_MODEL_REVISION": models["dense"].revision,
            "RETRIEVAL_DENSE_DIMENSION": str(models["dense"].dimension or 0),
            "RETRIEVAL_RERANKER_MODEL_ID": models["reranker"].model_id,
            "STRUCTURED_INDEX_ENABLED": _bool_text(self.features.structured_index),
            "RETRIEVAL_ENABLED": _bool_text(self.features.retrieval),
            "RETRIEVAL_DENSE_ENABLED": _bool_text(self.features.dense_retrieval),
            "RETRIEVAL_QDRANT_SPARSE_ENABLED": _bool_text(self.features.sparse_vectors),
            "RETRIEVAL_RERANKER_ENABLED": _bool_text(self.features.reranker),
            "RESEARCH_AGENT_ENABLED": _bool_text(self.features.research_agent),
            "ALIGNMENT_ENABLED": _bool_text(self.features.alignment),
            "OBSERVABILITY_ENABLED": _bool_text(self.features.observability),
            "OBSERVABILITY_API_ENABLED": _bool_text(self.features.observability_api),
            "EVALUATION_ENABLED": _bool_text(self.features.evaluation),
            "EVALUATION_API_ENABLED": _bool_text(self.features.evaluation_api),
            "EVALUATION_LIVE_ENABLED": _bool_text(self.features.evaluation_live),
        }
        optional = {
            "REDIS_URL": self.services.redis_url,
            "CELERY_BROKER_URL": self.services.celery_broker_url,
            "QDRANT_URL": self.services.qdrant_url,
            "S3_ENDPOINT_URL": self.artifacts.s3_endpoint_url,
            "S3_BUCKET": self.artifacts.s3_bucket,
        }
        for key, value in {**values, **optional}.items():
            if value is not None:
                previous = os.environ.get(key)
                if previous is not None and previous != str(value):
                    warnings.warn(
                        f"ignored legacy environment override because YAML is authoritative: {key}",
                        DeprecationWarning,
                        stacklevel=2,
                    )
                os.environ[key] = str(value)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"configuration file not found: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("configuration root must be a mapping")
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_path(value: Path | None, root: Path) -> Path | None:
    if value is None:
        return None
    expanded = value.expanduser()
    return expanded if expanded.is_absolute() else (root / expanded).resolve()


def _resolve_database_url(value: str, root: Path) -> str:
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    path = Path(value[len(prefix):]).expanduser()
    resolved = path if path.is_absolute() else (root / path).resolve()
    return f"sqlite:///{resolved}"


def _sqlite_data_root(value: str) -> Path:
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return Path("data").resolve()
    return Path(value[len(prefix):]).resolve().parent


def _sqlite_path_or(value: str, fallback: Path) -> Path:
    prefix = "sqlite:///"
    return Path(value[len(prefix):]).resolve() if value.startswith(prefix) else fallback.resolve()


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
