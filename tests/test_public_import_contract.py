"""Contracts for the package-level imports and dynamically registered API routes."""

from backend.app.image_generation.providers import MockImageProvider
from backend.app.llm import LLMRuntime, LLMSettings, create_llm_runtime
from backend.app.llm.providers import DeepSeekProvider, MockProvider, QwenProvider
from backend.app.main import app
from backend.app.vision import VisionRuntime, VisionSettings, create_vision_runtime
from backend.app.vision.providers import MockVisionProvider


def test_documented_public_imports_remain_available() -> None:
    assert LLMRuntime and LLMSettings and create_llm_runtime
    assert VisionRuntime and VisionSettings and create_vision_runtime
    assert DeepSeekProvider and QwenProvider


def test_mock_providers_remain_available_from_public_provider_packages() -> None:
    assert MockProvider.__name__ == "MockProvider"
    assert MockVisionProvider.__name__ == "MockVisionProvider"
    assert MockImageProvider.__name__ == "MockImageProvider"


def test_provider_all_exports_match_supported_public_contract() -> None:
    from backend.app.image_generation import providers as image_providers
    from backend.app.llm import providers as llm_providers
    from backend.app.vision import providers as vision_providers

    assert set(llm_providers.__all__) == {"DeepSeekProvider", "QwenProvider", "MockProvider"}
    assert "MockVisionProvider" in vision_providers.__all__
    assert "MockImageProvider" in image_providers.__all__


def test_key_fastapi_routes_remain_registered_in_openapi() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/health",
        "/api/v2/runtime/public-config",
        "/api/v2/workspaces/{workspace_id}/settings/providers",
        "/api/v2/workspaces/{workspace_id}/settings/providers/{provider_id}",
        "/api/v2/workspaces/{workspace_id}/settings/providers/{provider_id}/validate",
        "/api/v2/workspaces/{workspace_id}/settings/providers/{provider_id}/test",
        "/api/v2/workspaces/{workspace_id}/projects/{project_id}/library/functions",
    }
    assert expected <= set(paths)
    legacy = [path for path in paths if not (path == "/health" or path.startswith("/api/v2/"))]
    assert legacy == []


def test_known_internal_cleanup_candidates_are_not_public_exports() -> None:
    from backend.app import schemas, services
    from backend.app.llm import exceptions

    internal_names = {
        "EvidenceValidationError",
        "FileTreeNode",
        "normalize_image_bytes_to_png",
        "task_output_dir",
    }
    exported = set(getattr(schemas, "__all__", ())) | set(getattr(services, "__all__", ()))
    exported |= set(getattr(exceptions, "__all__", ()))
    assert internal_names.isdisjoint(exported)


def test_v135_compatibility_fields_remain_deprecated_and_legacy_routes_are_hidden() -> None:
    schema = app.openapi()
    components = schema["components"]["schemas"]
    for model_name in ("ProviderSettingsUpdateRequest", "ProviderValidateRequest"):
        assert components[model_name]["properties"]["supports_async"]["deprecated"] is True
    assert "AnalysisTaskRequest" not in components
    assert "/analysis/tasks" not in schema["paths"]
    assert "/analysis/tasks/upload" not in schema["paths"]
