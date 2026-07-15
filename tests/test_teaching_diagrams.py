from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.image_generation.downloader import SafeImageDownloader
from backend.app.image_generation.exceptions import ImageGenerationError
from backend.app.image_generation.providers.mock_provider import MockImageProvider
from backend.app.image_generation.router import ImageGenerationRouter
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.cache import ImageGenerationCache
from backend.app.image_generation.runtime import create_image_generation_runtime
from backend.app.image_generation.providers.qwen_image_provider import QwenImageProvider
from backend.app.image_generation.types import ImageGenerationRequest
from backend.app.llm.budget import BudgetManager
from backend.app.schemas.teaching_diagram import TeachingDiagramNarrative, TeachingDiagramSpec
from backend.app.services.analysis_service import run_analysis
from backend.app.teaching_diagrams.blueprint_renderer import BlueprintRenderer, CARD_H, CARD_W, layout_modules
from backend.app.teaching_diagrams.compositor import TeachingDiagramCompositor
from backend.app.teaching_diagrams.narrative import build_local_narrative
from backend.app.teaching_diagrams.skeleton_builder import build_teaching_diagram_skeletons
from backend.app.teaching_diagrams.spec_assembler import assemble_teaching_diagram_spec
from backend.app.vision.config import VisionSettings
from backend.app.vision.providers.mock_provider import MockVisionProvider
from backend.app.vision.runtime import create_vision_runtime

import fitz
import httpx
from fastapi.testclient import TestClient

from backend.app.main import app


def test_skeleton_builder_uses_mermaid_mapping_and_rule_evidence():
    result = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[],
        library_calls=[],
        model_analysis=[_model_analysis()],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[{"id": "model_flow", "diagram_type": "model_flow"}],
        max_diagrams=4,
    )

    assert result.skeletons
    skeleton = result.skeletons[0]
    assert skeleton.related_mermaid_diagram_ids == ["model_flow"]
    assert skeleton.connections
    valid_evidence = {item.evidence_id for item in result.evidence_catalog}
    assert all(ref in valid_evidence for module in skeleton.modules for ref in module.evidence_refs)
    assert all(ref in valid_evidence for edge in skeleton.connections for ref in edge.evidence_refs)


def test_evidence_ids_include_file_path_for_same_named_functions_and_models():
    result = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[
            {**_function_analysis("a/process.py", "process"), "is_core_function": True},
            {**_function_analysis("b/process.py", "process"), "is_core_function": True},
        ],
        library_calls=[],
        model_analysis=[
            {**_model_analysis(), "file_path": "a/model.py"},
            {**_model_analysis(), "file_path": "b/model.py", "is_main_model_candidate": False},
        ],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[],
        max_diagrams=4,
    )

    evidence_ids = {item.evidence_id for item in result.evidence_catalog}
    assert any("a_model_py" in item and "SimpleNet" in item for item in evidence_ids)
    assert any("b_model_py" in item and "SimpleNet" in item for item in evidence_ids)
    assert any("a_process_py" in item and "process" in item for item in evidence_ids)
    assert any("b_process_py" in item and "process" in item for item in evidence_ids)


def test_narrative_cannot_change_skeleton_identity():
    skeleton = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[],
        library_calls=[],
        model_analysis=[_model_analysis()],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[{"id": "model_flow", "diagram_type": "model_flow"}],
    ).skeletons[0]
    bad = TeachingDiagramNarrative(
        skeleton_id=skeleton.skeleton_id,
        skeleton_hash="0" * 64,
        one_sentence_summary="模型被 LLM 改成了不存在的模块",
    )

    spec = assemble_teaching_diagram_spec(skeleton, bad)

    assert isinstance(spec, TeachingDiagramSpec)
    assert [module.id for module in spec.modules] == [module.id for module in skeleton.modules]
    assert [edge.id for edge in spec.connections] == [edge.id for edge in skeleton.connections]
    assert any("身份不匹配" in warning for warning in spec.warnings)


def test_unknown_shapes_are_omitted_with_warning():
    skeleton = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[],
        library_calls=[],
        model_analysis=[_model_analysis()],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[],
    ).skeletons[0]

    assert skeleton.shapes == []
    assert any("已省略未确认 Shape" in warning for warning in skeleton.warnings)


def test_project_level_file_order_is_not_called_data_flow():
    skeleton = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[
            {"file_path": "main.py", "file_type": "entry", "confidence": "high"},
            {"file_path": "dataset.py", "file_type": "dataset", "confidence": "medium"},
            {"file_path": "model.py", "file_type": "model", "confidence": "medium"},
        ],
        function_analysis=[],
        library_calls=[],
        model_analysis=[],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[{"id": "project_structure", "diagram_type": "project_structure"}],
    ).skeletons[0]

    assert skeleton.source_entity.title == "项目建议阅读顺序"
    assert skeleton.sections[0].title == "项目建议阅读顺序"
    assert all(connection.label == "建议阅读顺序" for connection in skeleton.connections)


def test_blueprint_layout_for_ten_modules_has_no_duplicate_or_overlapping_coords():
    skeleton = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[],
        library_calls=[],
        model_analysis=[_model_analysis(forward_count=10)],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[],
    ).skeletons[0]
    spec = assemble_teaching_diagram_spec(skeleton, build_local_narrative(skeleton))
    layout = layout_modules(spec)
    coords = list(layout.values())

    assert len(coords) == len(set(coords))
    rects = [(x, y, x + CARD_W, y + CARD_H) for x, y in coords]
    for index, first in enumerate(rects):
        for second in rects[index + 1:]:
            assert first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1] or second[3] <= first[1]


def test_blueprint_renderer_escapes_svg_and_handles_long_chinese_text(tmp_path: Path):
    skeleton = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[],
        library_calls=[],
        model_analysis=[_model_analysis()],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[],
    ).skeletons[0]
    narrative = build_local_narrative(skeleton).model_copy(update={
        "one_sentence_summary": "中文说明<script>alert(1)</script>非常非常非常非常非常非常非常非常非常长"
    })

    with pytest.raises(ValueError):
        assemble_teaching_diagram_spec(skeleton, narrative)

    spec = assemble_teaching_diagram_spec(skeleton, build_local_narrative(skeleton))
    assets = BlueprintRenderer().render(spec, tmp_path)
    svg_text = Path(assets["svg"].path).read_text(encoding="utf-8")
    assert "<script" not in svg_text.lower()
    assert Path(assets["png"].path).is_file()


def test_compositor_uses_raw_background_and_keeps_deterministic_overlay(tmp_path: Path):
    skeleton = build_teaching_diagram_skeletons(
        repo_index={},
        file_analysis=[],
        function_analysis=[],
        library_calls=[],
        model_analysis=[_model_analysis()],
        paper_analysis={},
        paper_code_alignment={},
        diagrams=[],
    ).skeletons[0]
    spec = assemble_teaching_diagram_spec(skeleton, build_local_narrative(skeleton))
    assets = BlueprintRenderer().render(spec, tmp_path)
    raw_a = tmp_path / "raw_a.png"
    raw_b = tmp_path / "raw_b.png"
    raw_a.write_bytes(_solid_png((0.2, 0.5, 0.9)))
    raw_b.write_bytes(_solid_png((0.9, 0.5, 0.2)))

    composite_a = TeachingDiagramCompositor().compose(
        spec=spec,
        blueprint_png=Path(assets["png"].path),
        ai_dir=tmp_path / "ai",
        generated_raw=raw_a,
    )
    composite_b = TeachingDiagramCompositor().compose(
        spec=spec,
        blueprint_png=Path(assets["png"].path),
        ai_dir=tmp_path / "ai_b",
        generated_raw=raw_b,
    )
    styled_path = Path(composite_a["styled_composite"].path)

    assert composite_a["styled_composite"].sha256 != composite_b["styled_composite"].sha256
    assert composite_a["styled_composite"].sha256 != assets["png"].sha256
    assert composite_a["styled_composite"].sha256 != _sha256(raw_a)
    assert _has_dark_overlay_pixel(styled_path)


def test_safe_image_downloader_blocks_ssrf_targets():
    downloader = SafeImageDownloader(["example.com"], timeout_seconds=1, max_bytes=1000)
    with pytest.raises(ImageGenerationError):
        downloader.download("file:///tmp/x.png")
    with pytest.raises(ImageGenerationError):
        downloader.download("https://localhost/x.png")
    with pytest.raises(ImageGenerationError):
        downloader.download("https://169.254.169.254/latest/meta-data")


def test_image_router_unknown_provider_exception_counts_failed_request(tmp_path: Path):
    settings = ImageGenerationSettings.from_env(False)
    provider = MockImageProvider(error=lambda _request: RuntimeError("boom"))
    budget = BudgetManager(4, 1)
    router = ImageGenerationRouter(
        settings,
        [provider],
        budget,
        ImageGenerationCache(str(tmp_path / "cache.sqlite3"), str(tmp_path / "cache"), enabled=False),
    )
    result = router.generate(ImageGenerationRequest(
        diagram_id="td_test",
        public_spec={"public_spec_hash": "a" * 64},
        prompt_version="test",
        schema_version="1.3.1",
        width=320,
        height=180,
        mime_type="image/png",
        max_output_bytes=1024 * 1024,
        output_dir=tmp_path,
    ))

    assert result.image_path is None
    assert any(warning["code"] == "image_provider_unknown_error" for warning in result.warnings)
    assert budget.snapshot()["sent_provider_requests"] == 1


def test_workflow_generates_blueprint_without_external_requests(tmp_path: Path):
    state = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path,
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=False,
    )

    manifest = state["teaching_diagram_manifest"]
    assert manifest["status"] == "blueprint_only"
    assert 0 <= len(manifest["diagrams"]) <= 4
    assert state["teaching_image_budget"]["sent_provider_requests"] == 0
    for item in manifest["diagrams"]:
        assert (Path(state["output_dir"]) / item["blueprint_png"]["path"]).is_file()


def test_review_skips_without_ai_images(tmp_path: Path):
    provider = MockVisionProvider("qwen_vl", response=_review_response)
    vision_runtime = create_vision_runtime(VisionSettings.from_env(False), [provider])
    state = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path,
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=False,
        teaching_review_vlm_enabled=True,
        external_vision_consent=True,
        vision_runtime=vision_runtime,
    )

    assert provider.calls == []
    assert state["teaching_diagram_manifest"]["diagrams"][0]["display_variant"] == "blueprint"
    assert state["teaching_diagram_manifest"]["diagrams"][0]["review"] is None


def test_teaching_review_uses_mock_vision_and_cache_hit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEACHING_REVIEW_CACHE_PATH", str(tmp_path / "review.sqlite3"))
    image_settings = ImageGenerationSettings.from_env(True, True, True).model_copy(update={"cache_enabled": False})
    image_runtime = create_image_generation_runtime(image_settings, [MockImageProvider("qwen_image")])
    first_provider = MockVisionProvider("qwen_vl", response=_review_response)
    first_vision = create_vision_runtime(VisionSettings.from_env(False), [first_provider])
    first = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path / "first",
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=True,
        external_image_consent=True,
        teaching_review_vlm_enabled=True,
        external_vision_consent=True,
        image_runtime=image_runtime,
        vision_runtime=first_vision,
    )
    second_image_runtime = create_image_generation_runtime(image_settings, [MockImageProvider("qwen_image")])
    second_provider = MockVisionProvider("qwen_vl", response=_review_response)
    second_vision = create_vision_runtime(VisionSettings.from_env(False), [second_provider])
    second = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path / "second",
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=True,
        external_image_consent=True,
        teaching_review_vlm_enabled=True,
        external_vision_consent=True,
        image_runtime=second_image_runtime,
        vision_runtime=second_vision,
    )

    assert first["teaching_diagram_manifest"]["diagrams"][0]["review"]["metadata"]["cache_hit"] is False
    assert second["teaching_diagram_manifest"]["diagrams"][0]["review"]["metadata"]["cache_hit"] is True
    assert first_provider.calls
    assert second_provider.calls == []


def test_review_failure_triggers_seedream_regeneration(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEACHING_REVIEW_CACHE_PATH", str(tmp_path / "review_retry.sqlite3"))
    qwen = MockImageProvider("qwen_image", image_bytes=lambda _request: _solid_png((0.1, 0.1, 0.8)))
    seedream = MockImageProvider("seedream", image_bytes=lambda _request: _solid_png((0.1, 0.7, 0.2)))
    image_settings = ImageGenerationSettings.from_env(True, True, True).model_copy(update={"cache_enabled": False})
    image_runtime = create_image_generation_runtime(image_settings, [qwen, seedream])
    calls = {"count": 0}

    def review(request):
        calls["count"] += 1
        return _review_response(request, passed=calls["count"] > 1)

    vision_runtime = create_vision_runtime(VisionSettings.from_env(False), [MockVisionProvider("qwen_vl", response=review)])
    state = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path,
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=True,
        external_image_consent=True,
        teaching_review_vlm_enabled=True,
        external_vision_consent=True,
        image_runtime=image_runtime,
        vision_runtime=vision_runtime,
    )

    item = state["teaching_diagram_manifest"]["diagrams"][0]
    assert calls["count"] >= 2
    assert qwen.calls
    assert seedream.calls
    assert item["display_variant"] == "ai"
    assert item["final_asset"]["sha256"] == item["styled_composite"]["sha256"]


def test_qwen_image_provider_uses_dashscope_message_mapping():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = __import__("json").loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://dashscope.aliyuncs.com/result.png"}]}}
                ]
            }
        })

    settings = ImageGenerationSettings.from_env(False).qwen_image.model_copy(update={
        "api_key": "test-key",
        "base_url": "https://dashscope.aliyuncs.com",
        "endpoint_path": "/api/v1/services/aigc/multimodal-generation/generation",
        "workspace": "ws-1",
    })
    provider = QwenImageProvider(settings, transport=httpx.MockTransport(handler))
    response = provider.generate_image(ImageGenerationRequest(
        diagram_id="td_test",
        public_spec={"public_spec_hash": "a" * 64, "modules": []},
        prompt_version="test",
        schema_version="1.3.1",
        width=1280,
        height=720,
        mime_type="image/png",
        max_output_bytes=1024 * 1024,
        output_dir=Path("."),
    ))

    assert captured["url"].endswith("/api/v1/services/aigc/multimodal-generation/generation")
    assert captured["headers"]["x-dashscope-workspace"] == "ws-1"
    assert captured["json"]["input"]["messages"][0]["content"][0]["text"]
    assert captured["json"]["parameters"]["size"] == "1280*720"
    assert response.remote_url == "https://dashscope.aliyuncs.com/result.png"


def test_image_cache_hit_copies_raw_to_current_task_and_api_returns_200(tmp_path: Path):
    settings = ImageGenerationSettings.from_env(True, True, False).model_copy(update={
        "cache_enabled": True,
        "cache_path": str(tmp_path / "image_cache.sqlite3"),
        "cache_asset_root": str(tmp_path / "image_cache"),
    })
    first_runtime = create_image_generation_runtime(settings, [MockImageProvider("qwen_image")])
    first = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path / "first",
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=True,
        external_image_consent=True,
        teaching_review_vlm_enabled=False,
        image_runtime=first_runtime,
    )
    second_provider = MockImageProvider("qwen_image")
    second_runtime = create_image_generation_runtime(settings, [second_provider])
    second = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path / "second",
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=True,
        external_image_consent=True,
        teaching_review_vlm_enabled=False,
        image_runtime=second_runtime,
    )
    item = second["teaching_diagram_manifest"]["diagrams"][0]
    raw_path = Path(second["output_dir"]) / item["generated_raw"]["path"]

    assert raw_path.is_file()
    assert second_provider.calls == []
    response = TestClient(app).get(
        f"/analysis/tasks/{second['task_id']}/teaching-diagrams/{item['diagram_id']}/raw.png",
        params={"output_root": str(tmp_path / "second")},
    )
    assert first["teaching_diagram_manifest"]["diagrams"][0]["generated_raw"]["sha256"] == item["generated_raw"]["sha256"]
    assert response.status_code == 200


def _function_analysis(file_path: str, qualified_name: str) -> dict:
    return {
        "file_path": file_path,
        "qualified_name": qualified_name,
        "function_name": qualified_name,
        "start_line": 1,
        "implementation_logic": ["读取输入", "返回输出"],
        "outputs": ["result"],
    }


def _model_analysis(forward_count: int = 2) -> dict:
    steps = [
        {
            "order": index,
            "target": f"x{index}",
            "expression": f"self.fc{index}(x)",
            "uses_layers": [f"fc{index}"],
            "line_no": 11 + index,
            "explanation": f"第 {index} 层",
        }
        for index in range(1, forward_count + 1)
    ]
    return {
        "class_name": "SimpleNet",
        "file_path": "models/simple_model.py",
        "start_line": 5,
        "is_main_model_candidate": True,
        "model_inputs": ["x"],
        "model_outputs": ["logits"],
        "layers": [
            {"assigned_name": f"fc{index}", "name": f"fc{index}", "layer_type": "torch.nn.Linear", "line_no": 7 + index, "role": "classifier"}
            for index in range(1, forward_count + 1)
        ],
        "forward_steps": steps,
    }


def _review_response(request, passed: bool = True) -> dict:
    return {
        "diagram_id": request.context_id,
        "passed": passed,
        "overall_score": 92 if passed else 60,
        "accuracy_score": 5 if passed else 2,
        "spec_coverage_score": 5 if passed else 2,
        "label_readability_score": 4,
        "beginner_clarity_score": 4,
        "safety_score": 5,
        "recommendation": "pass" if passed else "fallback_blueprint",
    }


def _solid_png(color: tuple[float, float, float]) -> bytes:
    document = fitz.open()
    page = document.new_page(width=1280, height=720)
    page.draw_rect(fitz.Rect(0, 0, 1280, 720), fill=color, color=None)
    data = page.get_pixmap(alpha=False).tobytes("png")
    document.close()
    return data


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_dark_overlay_pixel(path: Path) -> bool:
    pixmap = fitz.Pixmap(str(path))
    # Sample around the first module border; raw test images are bright solids,
    # so a dark pixel here indicates deterministic overlay drawing is present.
    for x in range(50, 280, 8):
        for y in range(168, 260, 8):
            idx = (y * pixmap.width + x) * pixmap.n
            rgb = pixmap.samples[idx: idx + 3]
            if len(rgb) == 3 and max(rgb) < 190:
                return True
    return False
