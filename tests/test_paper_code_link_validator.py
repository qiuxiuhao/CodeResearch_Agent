from __future__ import annotations

import pytest

from backend.app.llm.budget import BudgetManager
from backend.app.llm.cache import LLMCache
from backend.app.llm.config import LLMSettings
from backend.app.llm.evidence import make_evidence
from backend.app.llm.paper_code_link_validator import PaperCodeLinkValidator
from backend.app.llm.providers.mock_provider import MockProvider
from backend.app.llm.router import ModelRouter
from backend.app.schemas.llm_explanation import PaperCodeAlignLLMExplanation


FIGURE_ID = "fig_1234567890abcdef1234"
TARGET_ID = "alignment:C1:target:abc"


def _evidence():
    rule = make_evidence("alignment:C1:rule", "paper_alignment_rule", "规则对齐")
    target = make_evidence(
        TARGET_ID, "paper_code_target", "模型实现目标", file_path="models/net.py",
        class_name="Net", rule_field="paper_code_alignment.matched_targets",
    )
    return rule, target


def _response(*, figure_id=FIGURE_ID, contribution_id="C1", code_refs=None):
    return {
        "contribution_id": "C1", "contribution_title": "Architecture",
        "alignment_summary": "规则事实支持候选关联。", "evidence_interpretation": [],
        "teaching_explanation": "该实现可能对应论文架构。", "needs_review": True,
        "uncertainties": [], "evidence_refs": ["alignment:C1:rule"],
        "possible_code_links": [{
            "figure_id": figure_id, "contribution_id": contribution_id,
            "code_evidence_refs": code_refs or [TARGET_ID], "reason": "建议关联",
            "confidence": "medium", "uncertainties": [], "suggested": True,
        }],
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"figure_id": "fig_ffffffffffffffffffff"}, "Figure"),
        ({"contribution_id": "C2"}, "contribution"),
        ({"code_refs": ["alignment:C1:rule"]}, "code evidence"),
    ],
)
def test_paper_code_link_validator_rejects_invalid_links(overrides, message):
    rule, target = _evidence()
    value = PaperCodeAlignLLMExplanation.model_validate(_response(**overrides))
    validator = PaperCodeLinkValidator(
        contribution_id="C1", allowed_figure_ids=[FIGURE_ID], code_evidence_catalog=[target]
    )

    with pytest.raises(ValueError, match=message):
        validator.validate(value)


def test_paper_code_link_validator_accepts_real_code_target():
    _rule, target = _evidence()
    value = PaperCodeAlignLLMExplanation.model_validate(_response())
    PaperCodeLinkValidator(
        contribution_id="C1", allowed_figure_ids=[FIGURE_ID], code_evidence_catalog=[target]
    ).validate(value)


def test_invalid_link_is_failed_before_provider_success_is_recorded(tmp_path):
    rule, target = _evidence()
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_enabled": False, "cache_path": str(tmp_path / "cache.sqlite3"), "max_retries": 0,
    })
    budget = BudgetManager(1, 1)
    provider = MockProvider("deepseek", responses={
        "paper_code_align": _response(code_refs=["alignment:C1:rule"])
    })
    validator = PaperCodeLinkValidator(
        contribution_id="C1", allowed_figure_ids=[FIGURE_ID], code_evidence_catalog=[target]
    )
    result = ModelRouter(
        settings, [provider], budget, LLMCache(settings.cache_path, enabled=False)
    ).generate_structured(
        task_type="paper_code_align", context_id="C1", system_prompt="json", input_payload={},
        response_model=PaperCodeAlignLLMExplanation, evidence_catalog=[rule, target],
        identity_validator=lambda value: value.contribution_id == "C1",
        result_validator=validator.validate,
    )

    assert result.value is None
    assert budget.snapshot()["sent_provider_requests"] == 1
    assert budget.snapshot()["successful_provider_requests"] == 0
    assert any(item["code"] == "llm_invalid_code_link" for item in result.warnings)


def test_invalid_cached_link_is_revalidated_and_never_returned(tmp_path):
    rule, target = _evidence()
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_enabled": True, "cache_path": str(tmp_path / "cache.sqlite3"), "max_retries": 0,
    })
    cache = LLMCache(settings.cache_path, enabled=True)
    provider = MockProvider("deepseek", responses={
        "paper_code_align": _response(code_refs=["alignment:C1:rule"])
    })
    first_budget = BudgetManager(1, 1)
    common = dict(
        task_type="paper_code_align", context_id="C1", system_prompt="json", input_payload={},
        response_model=PaperCodeAlignLLMExplanation, evidence_catalog=[rule, target],
        identity_validator=lambda value: value.contribution_id == "C1",
    )
    assert ModelRouter(settings, [provider], first_budget, cache).generate_structured(**common).value is not None

    second_budget = BudgetManager(1, 1)
    validator = PaperCodeLinkValidator(
        contribution_id="C1", allowed_figure_ids=[FIGURE_ID], code_evidence_catalog=[target]
    )
    result = ModelRouter(settings, [provider], second_budget, cache).generate_structured(
        **common, result_validator=validator.validate
    )

    assert result.value is None
    assert second_budget.snapshot()["cache_hits"] == 0
    assert second_budget.snapshot()["successful_provider_requests"] == 0
    assert any(item["code"] == "llm_cache_error" for item in result.warnings)
