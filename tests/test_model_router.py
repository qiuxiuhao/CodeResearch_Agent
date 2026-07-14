import json
import sqlite3

from backend.app.llm.budget import BudgetManager
from backend.app.llm.cache import LLMCache
from backend.app.llm.config import LLMSettings
from backend.app.llm.evidence import make_evidence
from backend.app.llm.exceptions import ProviderError
from backend.app.llm.providers.mock_provider import MockProvider
from backend.app.llm.router import ModelRouter
from backend.app.schemas.llm_explanation import FileLLMExplanation, FunctionLLMExplanation, PaperCodeAlignLLMExplanation


def _response():
    return {
        "file_path": "main.py", "summary": "入口文件", "architecture_role": "启动项目",
        "reading_guide": ["先读 main"], "key_relationships": [], "uncertainties": [],
        "evidence_refs": ["file:main.py"],
    }


def test_router_falls_back_and_counts_real_requests(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={"cache_path": str(tmp_path / "cache.sqlite3"), "max_retries": 0})
    budget = BudgetManager(5, 5)
    primary = MockProvider("deepseek", error=ProviderError("llm_timeout", "timeout"))
    backup = MockProvider("qwen", responses={"file_explain": _response()})
    router = ModelRouter(settings, [primary, backup], budget, LLMCache(settings.cache_path))
    evidence = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py")]
    result = router.generate_structured(
        task_type="file_explain", context_id="main.py", system_prompt="system",
        input_payload={"evidence_catalog": [item.model_dump() for item in evidence]},
        response_model=FileLLMExplanation, evidence_catalog=evidence,
    )
    assert result.value is not None
    assert result.value.metadata.fallback_used is True
    assert budget.snapshot()["sent_provider_requests"] == 2


def test_router_cache_hit_uses_no_second_request(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={"cache_path": str(tmp_path / "cache.sqlite3"), "max_retries": 0})
    budget = BudgetManager(5, 5)
    provider = MockProvider("deepseek", responses={"file_explain": _response()})
    router = ModelRouter(settings, [provider], budget, LLMCache(settings.cache_path))
    evidence = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py")]
    kwargs = dict(
        task_type="file_explain", context_id="main.py", system_prompt="system", input_payload={},
        response_model=FileLLMExplanation, evidence_catalog=evidence,
    )
    assert router.generate_structured(**kwargs).value is not None
    cached = router.generate_structured(**kwargs)
    assert cached.value.metadata.cache_hit is True
    assert len(provider.calls) == 1
    assert budget.snapshot()["sent_provider_requests"] == 1


def test_llm_cache_path_directory_falls_back_to_provider(tmp_path):
    cache_directory = tmp_path / "cache-dir"
    cache_directory.mkdir()
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(cache_directory), "cache_enabled": True, "max_retries": 0,
    })
    budget = BudgetManager(5, 5)
    provider = MockProvider("deepseek", responses={"file_explain": _response()})
    evidence = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py")]

    result = ModelRouter(settings, [provider], budget, LLMCache(settings.cache_path)).generate_structured(
        task_type="file_explain", context_id="main.py", system_prompt="system", input_payload={},
        response_model=FileLLMExplanation, evidence_catalog=evidence,
        identity_validator=lambda value: value.file_path == "main.py",
    )

    assert result.value is not None
    assert len(provider.calls) == 1
    assert "llm_cache_error" in result.value.metadata.warning_codes
    assert any(item["code"] == "llm_cache_error" for item in result.warnings)


def test_llm_cache_write_failure_keeps_validated_result(monkeypatch, tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(tmp_path / "readonly.sqlite3"), "cache_enabled": True, "max_retries": 0,
    })
    budget = BudgetManager(5, 5)
    provider = MockProvider("deepseek", responses={"file_explain": _response()})
    cache = LLMCache(settings.cache_path)
    monkeypatch.setattr(cache, "set", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError()))
    evidence = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py")]

    result = ModelRouter(settings, [provider], budget, cache).generate_structured(
        task_type="file_explain", context_id="main.py", system_prompt="system", input_payload={},
        response_model=FileLLMExplanation, evidence_catalog=evidence,
    )

    assert result.value is not None
    assert result.value.metadata.status == "success"
    assert "llm_cache_error" in result.value.metadata.warning_codes
    assert budget.snapshot()["successful_provider_requests"] == 1


def test_corrupt_llm_cache_json_is_ignored_and_provider_is_called(tmp_path):
    cache_path = tmp_path / "cache.sqlite3"
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(cache_path), "cache_enabled": True, "max_retries": 0,
    })
    evidence = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py")]
    common = dict(
        task_type="file_explain", context_id="main.py", system_prompt="system", input_payload={},
        response_model=FileLLMExplanation, evidence_catalog=evidence,
    )
    first_provider = MockProvider("deepseek", responses={"file_explain": _response()})
    assert ModelRouter(
        settings, [first_provider], BudgetManager(5, 5), LLMCache(str(cache_path))
    ).generate_structured(**common).value is not None
    with sqlite3.connect(cache_path) as connection:
        connection.execute("UPDATE llm_cache SET response_json='{broken-json'")

    second_provider = MockProvider("deepseek", responses={"file_explain": _response()})
    result = ModelRouter(
        settings, [second_provider], BudgetManager(5, 5), LLMCache(str(cache_path))
    ).generate_structured(**common)

    assert result.value is not None
    assert len(second_provider.calls) == 1
    assert any(item["code"] == "llm_cache_error" for item in result.warnings)


def test_http_success_with_invalid_schema_is_not_counted_as_success(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False, "max_retries": 0,
    })
    budget = BudgetManager(5, 5)
    provider = MockProvider("deepseek", responses={"file_explain": {"file_path": "main.py"}})
    router = ModelRouter(settings, [provider], budget, LLMCache(settings.cache_path, enabled=False))
    evidence = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py")]

    result = router.generate_structured(
        task_type="file_explain", context_id="main.py", system_prompt="system", input_payload={},
        response_model=FileLLMExplanation, evidence_catalog=evidence,
    )

    assert result.value is None
    assert budget.snapshot()["sent_provider_requests"] == 1
    assert budget.snapshot()["successful_provider_requests"] == 0


def test_long_function_input_stays_structured_and_preserves_identity_and_evidence(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False,
        "max_input_chars": 1000, "max_retries": 0,
    })
    budget = BudgetManager(5, 5)

    def response(request):
        analysis = request.input_payload["function_analysis"]
        return {
            "file_path": analysis["file_path"], "qualified_name": analysis["qualified_name"],
            "summary": "结构化输入仍可识别", "logic_summary": [],
            "teaching_explanation": "解释通过身份校验。", "key_points": [],
            "input_output_notes": [], "uncertainties": [],
            "evidence_refs": [request.input_payload["evidence_catalog"][0]["evidence_id"]],
        }

    provider = MockProvider("deepseek", responses={"function_explain": response})
    router = ModelRouter(settings, [provider], budget, LLMCache(settings.cache_path, enabled=False))
    evidence = [make_evidence(
        "function:pkg/a.py:process:1-3", "function_rule", "处理输入", file_path="pkg/a.py",
        function_name="process", start_line=1, end_line=3,
    )]
    payload = {
        "function_analysis": {
            "file_path": "pkg/a.py", "qualified_name": "process", "function_name": "process",
            "purpose": "处理输入", "implementation_logic": ["读取规则事实"],
        },
        "source": "def process(value):\n" + "    value += 1\n" * 2000,
        "instruction": "只根据规则事实解释函数。",
        "evidence_catalog": [item.model_dump() for item in evidence],
    }

    result = router.generate_structured(
        task_type="function_explain", context_id="pkg/a.py:process", system_prompt="system",
        input_payload=payload, response_model=FunctionLLMExplanation, evidence_catalog=evidence,
        identity_validator=lambda value: f"{value.file_path}:{value.qualified_name}" == "pkg/a.py:process",
    )

    assert result.value is not None
    sent = provider.calls[0].input_payload
    assert "truncated_input" not in sent
    assert sent["function_analysis"]["file_path"] == "pkg/a.py"
    assert sent["function_analysis"]["qualified_name"] == "process"
    assert sent["evidence_catalog"][0]["evidence_id"] == evidence[0].evidence_id
    assert "[TRUNCATED]" in sent["source"]
    assert len(json.dumps(sent, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= settings.max_input_chars
    assert result.value.metadata.input_truncated is True
    assert "llm_input_truncated" in result.value.metadata.warning_codes


def test_suggested_code_link_cannot_reference_unknown_code_evidence(tmp_path):
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(tmp_path / "cache.sqlite3"), "cache_enabled": False, "max_retries": 0,
    })
    budget = BudgetManager(1, 1)
    response = {
        "contribution_id": "C1", "contribution_title": "Architecture",
        "alignment_summary": "规则对齐支持该建议。", "evidence_interpretation": [],
        "teaching_explanation": "Figure 与实现可能相关。", "needs_review": True,
        "uncertainties": [], "evidence_refs": ["alignment:C1:rule"],
        "possible_code_links": [{
            "figure_id": "fig_1234567890abcdef1234", "contribution_id": "C1",
            "code_evidence_refs": ["unknown:code:target"], "reason": "无效引用",
            "confidence": "low", "uncertainties": [], "suggested": True,
        }],
    }
    provider = MockProvider("deepseek", responses={"paper_code_align": response})
    router = ModelRouter(settings, [provider], budget, LLMCache(settings.cache_path, enabled=False))
    evidence = [make_evidence("alignment:C1:rule", "paper_alignment_rule", "规则对齐")]

    result = router.generate_structured(
        task_type="paper_code_align", context_id="C1", system_prompt="system", input_payload={},
        response_model=PaperCodeAlignLLMExplanation, evidence_catalog=evidence,
        identity_validator=lambda value: value.contribution_id == "C1",
    )

    assert result.value is None
    assert budget.snapshot()["successful_provider_requests"] == 0
    assert any(item["code"] == "llm_invalid_evidence_reference" for item in result.warnings)
