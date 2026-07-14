from pathlib import Path

from backend.app.agents.nodes.paper_figure_analyze_vlm_node import paper_figure_analyze_vlm_node
from backend.app.agents.nodes.paper_figure_extract_node import paper_figure_extract_node
from backend.app.vision.config import VisionSettings
from backend.app.vision.providers.mock_provider import MockVisionProvider
from backend.app.vision.runtime import create_vision_runtime


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
    return {
        "figure_id": request.context_id,
        "figure_type": "architecture",
        "summary": "该图展示输入、编码器和输出。",
        "modules": [{"name": "Encoder", "role": "编码输入"}],
        "flows": [{"source": "Input", "target": "Encoder", "relation": "输入到编码器"}],
        "inputs": ["Input"], "outputs": ["Output"],
        "visual_relations": [{"subject": "Input", "relation": "流向", "object": "Encoder"}],
        "contribution_candidates": [{"contribution_id": "C1", "reason": "展示架构", "confidence": "medium"}],
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
