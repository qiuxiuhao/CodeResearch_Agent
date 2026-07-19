from __future__ import annotations

import os

from fastapi import HTTPException
import pytest

from backend.app.config.application import ApplicationConfig
_previous_config = os.environ.get("CRA_CONFIG_PATH")
os.environ["CRA_CONFIG_PATH"] = "config/local-cpu.yaml"
from backend.app.retrieval.inference_server import InferenceRuntime, _bounded
if _previous_config is None:
    os.environ.pop("CRA_CONFIG_PATH", None)
else:
    os.environ["CRA_CONFIG_PATH"] = _previous_config


def test_inference_batch_limit_is_enforced():
    with pytest.raises(HTTPException) as exc:
        _bounded(["one", "two"], 1)
    assert exc.value.status_code == 413
    assert exc.value.detail == "inference_batch_too_large"


def test_single_inference_execution_group_rejects_overload():
    runtime = InferenceRuntime(ApplicationConfig())
    with runtime.execution_slot():
        assert runtime.health()["active_requests"] == 1
        with pytest.raises(HTTPException) as exc:
            with runtime.execution_slot():
                pass
        assert exc.value.status_code == 429
        assert exc.value.detail == "inference_queue_full"
    assert runtime.health()["active_requests"] == 0
