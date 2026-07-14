from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.image_generation.downloader import SafeImageDownloader
from backend.app.image_generation.exceptions import ImageGenerationError
from backend.app.image_generation.providers.mock_provider import MockImageProvider
from backend.app.image_generation.router import ImageGenerationRouter
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.cache import ImageGenerationCache
from backend.app.image_generation.types import ImageGenerationRequest
from backend.app.llm.budget import BudgetManager
from backend.app.schemas.teaching_diagram import TeachingDiagramNarrative, TeachingDiagramSpec
from backend.app.services.analysis_service import run_analysis
from backend.app.teaching_diagrams.blueprint_renderer import BlueprintRenderer
from backend.app.teaching_diagrams.compositor import TeachingDiagramCompositor
from backend.app.teaching_diagrams.narrative import build_local_narrative
from backend.app.teaching_diagrams.skeleton_builder import build_teaching_diagram_skeletons
from backend.app.teaching_diagrams.spec_assembler import assemble_teaching_diagram_spec


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


def test_compositor_does_not_use_raw_as_final(tmp_path: Path):
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
    raw = tmp_path / "raw.png"
    raw.write_bytes(b"not used")

    composite = TeachingDiagramCompositor().compose(
        spec=spec,
        blueprint_png=Path(assets["png"].path),
        ai_dir=tmp_path / "ai",
        generated_raw=raw,
    )

    assert composite["final"].sha256 == assets["png"].sha256
    assert composite["final"].sha256 != raw.read_bytes().hex()


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
        schema_version="1.3.0",
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
        assert Path(item["blueprint_png"]["path"]).is_file()


def test_teaching_review_cache_hit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEACHING_REVIEW_CACHE_PATH", str(tmp_path / "review.sqlite3"))
    first = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path / "first",
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=False,
        teaching_review_vlm_enabled=True,
        external_vision_consent=True,
    )
    second = run_analysis(
        "examples/small_pytorch_project.zip",
        output_root=tmp_path / "second",
        text_llm_enabled=False,
        vision_vlm_enabled=False,
        image_generation_enabled=False,
        teaching_review_vlm_enabled=True,
        external_vision_consent=True,
    )

    assert first["teaching_diagram_manifest"]["diagrams"][0]["review"]["metadata"]["cache_hit"] is False
    assert second["teaching_diagram_manifest"]["diagrams"][0]["review"]["metadata"]["cache_hit"] is True


def _model_analysis() -> dict:
    return {
        "class_name": "SimpleNet",
        "file_path": "models/simple_model.py",
        "start_line": 5,
        "is_main_model_candidate": True,
        "model_inputs": ["x"],
        "model_outputs": ["logits"],
        "layers": [
            {"assigned_name": "fc1", "name": "fc1", "layer_type": "torch.nn.Linear", "line_no": 8, "role": "classifier"},
            {"assigned_name": "fc2", "name": "fc2", "layer_type": "torch.nn.Linear", "line_no": 9, "role": "classifier"},
        ],
        "forward_steps": [
            {"order": 1, "target": "x", "expression": "self.fc1(x)", "uses_layers": ["fc1"], "line_no": 12, "explanation": "第一层线性变换"},
            {"order": 2, "target": "logits", "expression": "self.fc2(x)", "uses_layers": ["fc2"], "line_no": 13, "explanation": "输出 logits"},
        ],
    }
