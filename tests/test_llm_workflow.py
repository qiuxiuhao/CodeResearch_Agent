import json
from pathlib import Path

from backend.app.llm.config import LLMSettings, ProviderSettings
from backend.app.llm.providers.deepseek_provider import DeepSeekProvider
from backend.app.llm.providers.mock_provider import MockProvider
from backend.app.llm.runtime import create_llm_runtime
from backend.app.agents.nodes.paper_code_align_llm_node import paper_code_align_llm_node
from backend.app.services.analysis_service import run_analysis


def _evidence_ref(request):
    return request.input_payload["evidence_catalog"][0]["evidence_id"]


def _file_response(request):
    item = request.input_payload["file_analysis"]
    return {
        "file_path": item["file_path"], "summary": "AI 文件总结", "architecture_role": "项目模块",
        "reading_guide": ["先看规则事实"], "key_relationships": [], "uncertainties": [],
        "evidence_refs": [_evidence_ref(request)],
    }


def _function_response(request):
    item = request.input_payload["function_analysis"]
    return {
        "file_path": item["file_path"], "qualified_name": item["qualified_name"], "summary": "AI 函数总结",
        "logic_summary": ["遵循规则逻辑"], "teaching_explanation": "这是基于静态事实的教学解释。",
        "key_points": [], "input_output_notes": [], "uncertainties": [],
        "evidence_refs": [_evidence_ref(request)],
    }


def _model_response(request):
    item = request.input_payload["model_analysis"]
    return {
        "file_path": item["file_path"], "class_name": item["class_name"], "summary": "AI 模型总结",
        "data_flow_explanation": ["按 forward steps 流动"], "module_explanations": [],
        "learning_notes": [], "uncertainties": [], "evidence_refs": [_evidence_ref(request)],
    }


def test_hybrid_workflow_with_mock_provider(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "max_function_explanations": 3,
        "max_file_explanations": 2, "max_model_explanations": 1,
    })
    provider = MockProvider("deepseek", responses={
        "file_explain": _file_response,
        "function_explain": _function_response,
        "model_explain": _model_response,
    })
    runtime = create_llm_runtime(settings, [provider])
    state = run_analysis(
        "examples/small_pytorch_project.zip", tmp_path / "outputs", tmp_path / "library.sqlite3",
        analysis_mode="hybrid", external_model_consent=True, llm_runtime=runtime,
    )
    output_dir = Path(state["output_dir"])
    payload = json.loads((output_dir / "llm_explanations.json").read_text(encoding="utf-8"))
    assert payload["status"] in {"success", "partial"}
    assert payload["file_explanations"]
    assert payload["function_explanations"]
    assert payload["model_explanations"]
    assert payload["budget"]["selected_entities"] <= payload["budget"]["max_total_entities"]
    assert payload["budget"]["sent_provider_requests"] <= payload["budget"]["max_provider_requests"]
    function_calls = [call for call in provider.calls if call.task_type == "function_explain"]
    assert any(call.input_payload.get("model_context") for call in function_calls)
    assert "## AI 增强解释" in (output_dir / "report.md").read_text(encoding="utf-8")


def test_rule_workflow_writes_disabled_llm_output(tmp_path):
    state = run_analysis("examples/small_pytorch_project.zip", tmp_path / "outputs", tmp_path / "library.sqlite3")
    payload = json.loads((Path(state["output_dir"]) / "llm_explanations.json").read_text(encoding="utf-8"))
    assert payload["analysis_mode"] == "rule"
    assert payload["status"] == "disabled"
    assert payload["budget"]["sent_provider_requests"] == 0


def test_hybrid_without_configured_provider_is_skipped(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={"cache_path": str(tmp_path / "cache.sqlite3")})
    unavailable = DeepSeekProvider(
        ProviderSettings(name="deepseek", api_key="", base_url="https://example.test", model="chat"), 5
    )
    runtime = create_llm_runtime(settings, [unavailable])
    state = run_analysis(
        "examples/small_pytorch_project.zip", tmp_path / "outputs", tmp_path / "library.sqlite3",
        analysis_mode="hybrid", external_model_consent=True, llm_runtime=runtime,
    )
    payload = json.loads((Path(state["output_dir"]) / "llm_explanations.json").read_text(encoding="utf-8"))
    assert payload["status"] == "skipped"
    assert payload["budget"]["sent_provider_requests"] == 0
    assert (Path(state["output_dir"]) / "function_analysis.json").exists()


def test_paper_alignment_node_uses_structured_mock(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={"cache_path": str(tmp_path / "cache.sqlite3")})

    def response(request):
        item = request.input_payload["rule_alignment"]
        return {
            "contribution_id": item["contribution_id"], "contribution_title": item["contribution_title"],
            "alignment_summary": "规则证据支持该对应关系。", "evidence_interpretation": ["名称与函数一致"],
            "teaching_explanation": "这表示论文模块在对应函数中实现。", "needs_review": False,
            "uncertainties": [], "evidence_refs": [_evidence_ref(request)],
        }

    provider = MockProvider("deepseek", responses={"paper_code_align": response})
    runtime = create_llm_runtime(settings, [provider])
    state = {
        "analysis_mode": "hybrid", "paper_analysis": {"paper_provided": True, "contributions": [
            {"id": "C1", "title": "模块", "description": "不可信论文数据"}
        ]},
        "paper_code_alignment": {"alignment_items": [
            {"contribution_id": "C1", "contribution_title": "模块", "status": "matched", "reason": "规则匹配", "confidence": "high"}
        ]},
        "llm_warnings": [], "llm_evidence_catalog": [], "llm_skipped_entities": [],
    }
    result = paper_code_align_llm_node(state, runtime)
    assert result["paper_code_align_llm_explanations"][0]["contribution_id"] == "C1"
    assert provider.calls[0].task_type == "paper_code_align"
