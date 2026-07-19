from __future__ import annotations

import platform

import pytest

from backend.app.config.application import ApplicationConfig, ComputeSettings


def test_local_yaml_is_strict_and_cpu(tmp_path):
    path = tmp_path / "local.yaml"
    path.write_text(
        "schema_version: '2.0'\nprofile: local\ncompute:\n  device: cpu\n"
        "  execution_providers: [CPUExecutionProvider]\n",
        encoding="utf-8",
    )
    config = ApplicationConfig.load(path)
    assert config.profile == "local"
    assert config.compute.device == "cpu"


def test_unknown_yaml_field_is_rejected(tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text("schema_version: '2.0'\nunknown: true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ApplicationConfig.load(path)


def test_cuda_requires_linux_x86_and_cuda_provider():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        with pytest.raises(ValueError):
            ComputeSettings(device="cuda", execution_providers=["CUDAExecutionProvider"])
    with pytest.raises(ValueError):
        ComputeSettings(device="cpu", execution_providers=["CUDAExecutionProvider"])
