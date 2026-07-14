import json

import httpx

from backend.app.schemas.paper_figure import FigureAnalysis, VisionEvidenceItem
from backend.app.vision.config import VisionProviderSettings, VisionSettings
from backend.app.vision.providers.glm_v_provider import GLMVProvider
from backend.app.vision.exceptions import VisionProviderError
from backend.app.vision.providers.mock_provider import MockVisionProvider
from backend.app.vision.providers.qwen_vl_provider import QwenVLProvider
from backend.app.vision.runtime import create_vision_runtime
from backend.app.vision.types import VisionRequest


FIGURE_ID = "fig_1234567890abcdef1234"


def _response(request):
    evidence_id = request.input_payload["evidence_catalog"][0]["evidence_id"]
    return {
        "figure_id": FIGURE_ID,
        "figure_type": "architecture",
        "summary": "该图展示输入经过编码器得到输出。",
        "modules": [{"name": "Encoder", "role": "提取特征"}],
        "flows": [{"source": "Input", "target": "Encoder", "relation": "输入流向编码器"}],
        "inputs": ["Input"],
        "outputs": ["Output"],
        "visual_relations": [{"subject": "Input", "relation": "连接到", "object": "Encoder"}],
        "contribution_candidates": [{"contribution_id": "C1", "reason": "图注对应架构贡献", "confidence": "medium"}],
        "uncertainties": [],
        "evidence_refs": [evidence_id],
    }


def _request(runtime):
    evidence = [VisionEvidenceItem(
        evidence_id=f"figure:{FIGURE_ID}:region", evidence_type="figure",
        fact_summary="Figure region", figure_id=FIGURE_ID, page_number=1, confidence="high",
    )]
    payload = {
        "figure_id": FIGURE_ID,
        "caption": {"text": "Figure 1. Architecture"},
        "contribution_catalog": [{"id": "C1", "title": "Architecture"}],
        "evidence_catalog": [item.model_dump(mode="json") for item in evidence],
    }
    return runtime.router.analyze(
        context_id=FIGURE_ID, system_prompt="return json", input_payload=payload,
        image_bytes=b"synthetic-png", mime_type="image/png", evidence_catalog=evidence,
    )


def test_vision_router_validates_then_records_success(tmp_path):
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False, "max_retries": 0,
    })
    provider = MockVisionProvider("qwen_vl", response=_response)
    runtime = create_vision_runtime(settings, [provider])
    runtime.budget.try_reserve_entities("paper_figure_analyze", 1)

    result = _request(runtime)

    assert result.value is not None
    assert result.value.figure_id == FIGURE_ID
    assert not hasattr(result.value, "possible_code_links")
    snapshot = runtime.budget.snapshot()
    assert snapshot["sent_provider_requests"] == 1
    assert snapshot["successful_provider_requests"] == 1
    assert provider.capabilities.supports_json_object is False


def test_schema_failure_is_not_counted_as_success(tmp_path):
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False, "max_retries": 0,
    })
    provider = MockVisionProvider("qwen_vl", response={"figure_id": FIGURE_ID})
    runtime = create_vision_runtime(settings, [provider])
    runtime.budget.try_reserve_entities("paper_figure_analyze", 1)

    result = _request(runtime)

    assert result.value is None
    snapshot = runtime.budget.snapshot()
    assert snapshot["sent_provider_requests"] == 1
    assert snapshot["successful_provider_requests"] == 0


def test_vision_cache_hit_avoids_second_provider_request(tmp_path):
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": True, "max_retries": 0,
    })
    provider = MockVisionProvider("qwen_vl", response=_response)
    runtime = create_vision_runtime(settings, [provider])
    runtime.budget.try_reserve_entities("paper_figure_analyze", 1)

    first = _request(runtime)
    second = _request(runtime)

    assert first.value is not None and second.value is not None
    assert second.value.metadata.cache_hit is True
    assert len(provider.calls) == 1
    assert runtime.budget.snapshot()["cache_hits"] == 1


def test_invalid_contribution_candidate_fails_validation(tmp_path):
    def invalid(request):
        value = _response(request)
        value["contribution_candidates"][0]["contribution_id"] = "C999"
        return value

    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False, "max_retries": 0,
    })
    runtime = create_vision_runtime(settings, [MockVisionProvider("qwen_vl", response=invalid)])
    runtime.budget.try_reserve_entities("paper_figure_analyze", 1)
    result = _request(runtime)

    assert result.value is None
    assert any(item["code"] == "vlm_evidence_validation_failed" for item in result.warnings)


def test_vision_router_falls_back_to_glm_and_counts_requests(tmp_path):
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False, "max_retries": 0,
    })
    primary = MockVisionProvider("qwen_vl", error=VisionProviderError("vlm_timeout", "timeout"))
    backup = MockVisionProvider("glm_v", response=_response)
    runtime = create_vision_runtime(settings, [primary, backup])
    runtime.budget.try_reserve_entities("paper_figure_analyze", 1)

    result = _request(runtime)

    assert result.value is not None
    assert result.value.metadata.provider == "glm_v"
    assert result.value.metadata.fallback_used is True
    assert runtime.budget.snapshot()["sent_provider_requests"] == 2


def test_real_provider_adapters_default_to_prompt_json_without_response_format():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"ok": True})}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    providers = [
        QwenVLProvider(VisionProviderSettings(
            name="qwen_vl", api_key="test", base_url="https://qwen.test", model="vision",
        ), 5, client),
        GLMVProvider(VisionProviderSettings(
            name="glm_v", api_key="test", base_url="https://glm.test", model="vision",
        ), 5, client),
    ]
    request = VisionRequest(
        context_id=FIGURE_ID, system_prompt="system", input_payload={"figure_id": FIGURE_ID},
        image_bytes=b"png", mime_type="image/png", response_model=FigureAnalysis, max_output_tokens=100,
    )
    for provider in providers:
        provider.analyze_figure(request)

    assert len(captured) == 2
    assert all("response_format" not in payload for payload in captured)
    assert all(payload["messages"][1]["content"][0]["type"] == "image_url" for payload in captured)
