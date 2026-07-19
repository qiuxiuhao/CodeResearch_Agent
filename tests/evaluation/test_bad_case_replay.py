from __future__ import annotations

import asyncio

import pytest

from backend.app.evaluation.bad_case_service import BadCaseService
from backend.app.evaluation.mock_runner import build_synthetic_suite
from backend.app.evaluation.promotion_service import PromotionService
from backend.app.evaluation.replay_service import summarize_live_trials
from backend.app.evaluation.schemas import (
    BadCaseTransitionRequest,
    FixReference,
    RetrievalOutcome,
)
from backend.app.evaluation.store_protocol import EvaluationStoreError


def _failing_bad_case():
    suite = build_synthetic_suite()
    suite.outcomes["synthetic-retrieval-001"] = RetrievalOutcome(
        ranked_entity_ids=[], ranked_chunk_ids=[], channel_status={}
    )
    request = suite.request.model_copy(update={"components": ["retrieval"]})
    run = suite.service.prepare_run(request, caller_scope_hash="test")
    run = asyncio.run(suite.service.process_run(run.run_id))
    bad_case = next(iter(suite.store.bad_cases.values()))
    return suite, run, bad_case


def _confirm(suite, bad_case):
    service = BadCaseService(suite.store)
    triaged = service.transition(
        bad_case.bad_case_id,
        "triaged",
        BadCaseTransitionRequest(based_on_revision=bad_case.revision, reason_code="triaged"),
        actor_scope="reviewer",
    )
    return service.transition(
        bad_case.bad_case_id,
        "confirmed",
        BadCaseTransitionRequest(
            based_on_revision=triaged.revision,
            reason_code="confirmed",
            confirmed_root_cause="retrieval_miss",
        ),
        actor_scope="reviewer",
    )


def test_same_failure_adds_bad_case_occurrence():
    suite, _run, bad_case = _failing_bad_case()
    result = next(iter(suite.store.case_results.values())).model_copy(
        update={"result_id": "repeat-result", "evaluation_run_id": "repeat-run"}
    )
    case = suite.store.cases[result.case_id]
    suite.service.bad_case_analyzer.analyze(case=case, result=result, subject_id="subject-repeat")
    current = suite.store.get_bad_case(bad_case.bad_case_id)
    assert current.occurrence_count == 2


def test_different_symptom_creates_distinct_bad_case():
    suite, _run, bad_case = _failing_bad_case()
    result = next(iter(suite.store.case_results.values())).model_copy(
        update={
            "result_id": "different-result",
            "execution_status": "error",
            "evaluation_outcome": None,
            "execution_error_code": "provider_timeout",
            "quality_failure_codes": [],
            "complete": False,
        }
    )
    case = suite.store.cases[result.case_id]
    other = suite.service.bad_case_analyzer.analyze(case=case, result=result, subject_id="subject")
    assert other is not None
    assert other.bad_case_id != bad_case.bad_case_id


def test_bad_case_can_be_promoted_before_fix_exists():
    suite, _run, bad_case = _failing_bad_case()
    confirmed = _confirm(suite, bad_case)
    source_case = suite.store.cases[confirmed.case_id]
    regression_case = source_case.model_copy(
        update={
            "case_id": "regression-retrieval-001",
            "dataset_version_id": "synthetic-regression-v2",
            "split": "regression",
            "source": "confirmed_bad_case",
        }
    )
    promotion = PromotionService(suite.store).promote(
        bad_case_id=confirmed.bad_case_id,
        source_dataset_version_id="synthetic-regression-v1",
        target_dataset_version_id="synthetic-regression-v2",
        new_case_id=regression_case.case_id,
        source_trace_id=None,
        pre_fix_reproduction_result_id="pre-fix-result",
        reproduced=True,
        regression_case=regression_case,
    )
    assert promotion.fix_reference is None
    assert promotion.reproduction_status == "reproduced"
    assert suite.store.get_dataset_version("synthetic-regression-v2").status == "draft"


def test_fixed_status_requires_fix_reference():
    suite, _run, bad_case = _failing_bad_case()
    confirmed = _confirm(suite, bad_case)
    fixing = BadCaseService(suite.store).transition(
        confirmed.bad_case_id,
        "fixing",
        BadCaseTransitionRequest(based_on_revision=confirmed.revision, reason_code="work-started"),
        actor_scope="reviewer",
    )
    with pytest.raises(EvaluationStoreError, match="fix_reference_required"):
        BadCaseService(suite.store).transition(
            fixing.bad_case_id,
            "fixed",
            BadCaseTransitionRequest(based_on_revision=fixing.revision, reason_code="fixed"),
            actor_scope="reviewer",
        )


def test_configuration_fix_does_not_require_git_commit():
    suite, _run, bad_case = _failing_bad_case()
    confirmed = _confirm(suite, bad_case)
    fixing = BadCaseService(suite.store).transition(
        confirmed.bad_case_id,
        "fixing",
        BadCaseTransitionRequest(based_on_revision=confirmed.revision, reason_code="work-started"),
        actor_scope="reviewer",
    )
    fixed = BadCaseService(suite.store).transition(
        fixing.bad_case_id,
        "fixed",
        BadCaseTransitionRequest(
            based_on_revision=fixing.revision,
            reason_code="config-fixed",
            fix_reference=FixReference(
                fix_type="configuration", reference_id="config-v2", content_hash="a" * 64
            ),
        ),
        actor_scope="reviewer",
    )
    assert fixed.fix_reference.fix_type == "configuration"


def test_live_trial_summary_reports_variance_and_failure_rate():
    summary = summarize_live_trials("trial", [1.0, 0.0, None], [False, False, True])
    assert summary.repeat_count == 3
    assert summary.mean_score == 0.5
    assert summary.provider_failure_rate == pytest.approx(1 / 3)
