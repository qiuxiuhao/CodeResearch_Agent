from backend.app.llm.budget import BudgetManager
from backend.app.llm.cache import LLMCache
from backend.app.llm.config import LLMSettings
from backend.app.llm.evidence import make_evidence
from backend.app.llm.exceptions import ProviderError
from backend.app.llm.providers.mock_provider import MockProvider
from backend.app.llm.router import ModelRouter
from backend.app.schemas.llm_explanation import FileLLMExplanation


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
