from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.config.application import ApplicationConfig


class DoctorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: Literal["ok", "warning", "error"]
    detail: str


def run_doctor(config: ApplicationConfig) -> list[DoctorCheck]:
    checks = [
        DoctorCheck(
            name="python",
            status="ok" if sys.version_info[:2] == (3, 11) else "error",
            detail=platform.python_version(),
        ),
        _resource_check("cpu", os.cpu_count() or 1, config.resources.minimum_team_cpu_cores, config.profile),
        _memory_check(config),
        _disk_check(config),
        _module_check("yaml", required=True),
        _module_check("qdrant_client", required=config.compute.device in {"cpu", "cuda"}),
        _module_check("fastembed", required=True),
        _module_check("onnxruntime", required=True),
        _path_check("model_cache", config.compute.model_cache, required=False),
        _path_check("model_manifest", config.model_manifest, file=True),
    ]
    if config.compute.device == "cuda":
        checks.extend(_cuda_checks(config))
    if config.profile == "team":
        checks.extend([
            _command_check("psql"), _command_check("redis-cli"),
            _command_check("minio"), _command_check("qdrant"), _command_check("supervisord"),
            _tcp_check("postgres", "127.0.0.1", 5432),
            _tcp_check("redis", "127.0.0.1", 6379),
            _tcp_check("minio", "127.0.0.1", 9000),
            _tcp_check("qdrant", "127.0.0.1", 6333),
        ])
    return checks


def doctor_ok(checks: list[DoctorCheck]) -> bool:
    return not any(check.status == "error" for check in checks)


def _resource_check(name: str, actual: int, minimum: int, profile: str) -> DoctorCheck:
    required = minimum if profile == "team" else 1
    return DoctorCheck(name=name, status="ok" if actual >= required else "error", detail=f"{actual} (required {required})")


def _memory_check(config: ApplicationConfig) -> DoctorCheck:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        gib = int(pages * page_size / (1024 ** 3))
    except (ValueError, OSError, AttributeError):
        return DoctorCheck(name="memory", status="warning", detail="unavailable")
    required = config.resources.minimum_team_memory_gib if config.profile == "team" else 8
    return DoctorCheck(name="memory", status="ok" if gib >= required else "error", detail=f"{gib} GiB (required {required})")


def _disk_check(config: ApplicationConfig) -> DoctorCheck:
    target = config.artifacts.local_root
    existing = target if target.exists() else next((p for p in target.parents if p.exists()), Path.cwd())
    free = int(shutil.disk_usage(existing).free / (1024 ** 3))
    required = config.resources.minimum_team_disk_gib if config.profile == "team" else 5
    return DoctorCheck(name="disk", status="ok" if free >= required else "error", detail=f"{free} GiB free (required {required})")


def _module_check(name: str, *, required: bool) -> DoctorCheck:
    present = importlib.util.find_spec(name) is not None
    return DoctorCheck(
        name=f"python:{name}", status="ok" if present else ("error" if required else "warning"),
        detail="installed" if present else "missing",
    )


def _path_check(name: str, path: Path, *, file: bool = False, required: bool = True) -> DoctorCheck:
    present = path.is_file() if file else path.is_dir()
    return DoctorCheck(
        name=name,
        status="ok" if present else ("error" if required else "warning"),
        detail=str(path),
    )


def _command_check(name: str) -> DoctorCheck:
    value = shutil.which(name)
    return DoctorCheck(name=f"command:{name}", status="ok" if value else "error", detail=value or "missing")


def _tcp_check(name: str, host: str, port: int) -> DoctorCheck:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            pass
    except OSError as exc:
        return DoctorCheck(name=f"service:{name}", status="error", detail=type(exc).__name__)
    return DoctorCheck(name=f"service:{name}", status="ok", detail=f"{host}:{port}")


def _cuda_checks(config: ApplicationConfig) -> list[DoctorCheck]:
    command = _command_check("nvidia-smi")
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
    except Exception as exc:
        return [command, DoctorCheck(name="cuda_execution_provider", status="error", detail=type(exc).__name__)]
    required = config.compute.execution_providers[0]
    return [
        command,
        DoctorCheck(
            name="cuda_execution_provider",
            status="ok" if providers and providers[0] == required else "error",
            detail=",".join(providers),
        ),
    ]
