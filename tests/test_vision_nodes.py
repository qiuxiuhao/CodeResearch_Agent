from pathlib import Path

from backend.app.agents.nodes.paper_figure_analyze_vlm_node import paper_figure_analyze_vlm_node
from backend.app.agents.nodes.paper_figure_extract_node import paper_figure_extract_node
from backend.app.vision.config import VisionSettings
from backend.app.vision.providers.mock_provider import MockVisionProvider
from backend.app.vision.runtime import create_vision_runtime
from backend.app.services.analysis_service import run_analysis


def _write_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((50, 50), "Method")
    page.draw_rect(fitz.Rect(100, 120, 500, 320), color=(0, 0, 0), width=2)
    page.insert_text((150, 210), "Input -> Encoder -> Output")
    page.insert_textbox(fitz.Rect(70, 350, 530, 410), "Figure 1. Overview architecture of our method.", fontsize=11)
    document.save(path)
    document.close()


def _response(request):
    contribution_candidates = []
    if any(item.get("id") == "C1" for item in request.input_payload.get("contribution_catalog", [])):
        contribution_candidates = [{"contribution_id": "C1", "reason": "展示架构", "confidence": "medium"}]
    return {
        "figure_id": request.context_id,
        "figure_type": "architecture",
        "summary": "该图展示输入、编码器和输出。",
        "modules": [{"name": "Encoder", "role": "编码输入"}],
        "flows": [{"source": "Input", "target": "Encoder", "relation": "输入到编码器"}],
        "inputs": ["Input"], "outputs": ["Output"],
        "visual_relations": [{"subject": "Input", "relation": "流向", "object": "Encoder"}],
        "contribution_candidates": contribution_candidates,
        "uncertainties": [],
        "evidence_refs": [request.input_payload["evidence_catalog"][0]["evidence_id"]],
    }


def test_extract_and_vlm_nodes_keep_structured_figure_result(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_pdf(pdf)
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_enabled": False, "cache_path": str(tmp_path / "cache.sqlite3"), "max_retries": 0,
    })
    provider = MockVisionProvider("qwen_vl", response=_response)
    runtime = create_vision_runtime(settings, [provider])
    state = {
        "output_dir": str(tmp_path / "task"), "paper_pdf_path": str(pdf),
        "paper_analysis": {"paper_provided": True, "sections": [], "contributions": [
            {"id": "C1", "title": "Architecture", "description": "We propose an encoder.", "confidence": "high"}
        ]},
        "vision_vlm_enabled": True, "external_vision_consent": True,
    }

    extracted = paper_figure_extract_node(state, runtime)
    analyzed = paper_figure_analyze_vlm_node(extracted, runtime)

    figures = analyzed["paper_figure_analysis"]["figures"]
    assert len(figures) == 1
    assert figures[0]["canonical_preview"]
    assert figures[0]["vlm_analysis"]["figure_id"] == figures[0]["figure_id"]
    assert figures[0]["vlm_analysis"]["contribution_candidates"][0]["contribution_id"] == "C1"
    assert "possible_code_links" not in figures[0]["vlm_analysis"]
    assert analyzed["paper_figure_analysis"]["vision_status"] == "success"
    assert provider.calls[0].image_bytes


def test_vlm_node_rechecks_backend_consent_before_provider(tmp_path):
    settings = VisionSettings.from_env(True).model_copy(update={"cache_enabled": False})
    provider = MockVisionProvider("qwen_vl", response=_response)
    runtime = create_vision_runtime(settings, [provider])
    state = {
        "vision_vlm_enabled": True, "external_vision_consent": False,
        "paper_figure_analysis": {"figures": [], "warnings": []},
    }

    result = paper_figure_analyze_vlm_node(state, runtime)

    assert result["paper_figure_analysis"]["vision_status"] == "failed"
    assert result["paper_figure_analysis"]["warnings"][0]["code"] == "vlm_consent_required"
    assert provider.calls == []


def test_single_figure_unexpected_error_does_not_abort_other_figures(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_pdf(pdf)
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_enabled": False, "max_retries": 0, "max_figure_analyses": 2,
    })
    state = {
        "output_dir": str(tmp_path / "task"), "paper_pdf_path": str(pdf),
        "paper_analysis": {"paper_provided": True, "sections": [], "contributions": [
            {"id": "C1", "title": "Architecture", "description": "Encoder", "confidence": "high"}
        ]},
        "vision_vlm_enabled": True, "external_vision_consent": True,
    }
    extracted = paper_figure_extract_node(state, create_vision_runtime(settings, []))
    first = extracted["paper_figure_analysis"]["figures"][0]
    second = {
        **first,
        "figure_id": "fig_abcdefabcdefabcdefab",
        "vlm_analysis": None,
        "selection": {**first["selection"], "selected": True},
    }
    extracted["paper_figure_analysis"]["figures"] = [first, second]

    def response(request):
        if request.context_id == first["figure_id"]:
            raise RuntimeError("unexpected provider adapter failure")
        value = _response(request)
        value["figure_id"] = request.context_id
        return value

    provider = MockVisionProvider("qwen_vl", response=response)
    runtime = create_vision_runtime(settings, [provider])
    result = paper_figure_analyze_vlm_node(extracted, runtime)

    assert result["paper_figure_analysis"]["vision_status"] == "partial"
    assert any(
        item["code"] == "vlm_unexpected_provider_error"
        for item in result["paper_figure_analysis"]["warnings"]
    )
    assert any(item.get("vlm_analysis") for item in result["paper_figure_analysis"]["figures"])


def test_oversized_dimensions_are_downscaled_for_request_instead_of_skipped(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_pdf(pdf)
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_enabled": False, "max_retries": 0,
        "max_image_width": 128, "max_image_height": 128,
    })
    provider = MockVisionProvider("qwen_vl", response=_response)
    runtime = create_vision_runtime(settings, [provider])
    state = {
        "output_dir": str(tmp_path / "task"), "paper_pdf_path": str(pdf),
        "paper_analysis": {"paper_provided": True, "sections": [], "contributions": [
            {"id": "C1", "title": "Architecture", "description": "Encoder", "confidence": "high"}
        ]},
        "vision_vlm_enabled": True, "external_vision_consent": True,
    }
    extracted = paper_figure_extract_node(state, runtime)
    original = Path(
        extracted["paper_figure_analysis"]["figures"][0]["canonical_preview"]["path"]
    ).read_bytes()

    analyzed = paper_figure_analyze_vlm_node(extracted, runtime)

    assert analyzed["paper_figure_analysis"]["vision_status"] == "success"
    assert provider.calls
    assert provider.calls[0].image_bytes != original
    assert any(
        item["code"] == "vlm_request_preview_scaled"
        for item in analyzed["paper_figure_analysis"]["warnings"]
    )


def test_synthetic_pdf_and_mock_vision_provider_complete_workflow(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_pdf(pdf)
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_enabled": False, "max_retries": 0,
    })
    provider = MockVisionProvider("qwen_vl", response=_response)
    runtime = create_vision_runtime(settings, [provider])

    state = run_analysis(
        "examples/small_pytorch_project.zip", tmp_path / "outputs", tmp_path / "library.sqlite3",
        pdf, vision_vlm_enabled=True, external_vision_consent=True, vision_runtime=runtime,
    )

    output_dir = Path(state["output_dir"])
    assert state["paper_figure_analysis"]["vision_status"] == "success"
    assert state["paper_figure_analysis"]["figures"][0]["vlm_analysis"]
    assert (output_dir / "paper_figure_analysis.json").exists()
    assert (output_dir / "diagrams.json").exists()
    assert (output_dir / "library_function_docs.json").exists()
    assert (output_dir / "report.md").exists()


def test_unexpected_vision_failure_still_completes_rule_workflow(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_pdf(pdf)
    settings = VisionSettings.from_env(True).model_copy(update={
        "cache_enabled": False, "max_retries": 0,
    })

    def explode(_request):
        raise RuntimeError("unexpected adapter error")

    runtime = create_vision_runtime(settings, [MockVisionProvider("qwen_vl", response=explode)])
    state = run_analysis(
        "examples/small_pytorch_project.zip", tmp_path / "outputs", tmp_path / "library.sqlite3",
        pdf, vision_vlm_enabled=True, external_vision_consent=True, vision_runtime=runtime,
    )

    output_dir = Path(state["output_dir"])
    assert state["paper_figure_analysis"]["vision_status"] == "failed"
    assert state["paper_figure_analysis"]["budget"]["sent_provider_requests"] == 1
    assert state["paper_figure_analysis"]["budget"]["successful_provider_requests"] == 0
    assert any(
        item["code"] == "vlm_unexpected_provider_error"
        for item in state["paper_figure_analysis"]["warnings"]
    )
    assert (output_dir / "diagrams.json").exists()
    assert (output_dir / "library_function_docs.json").exists()
    assert (output_dir / "report.md").exists()
