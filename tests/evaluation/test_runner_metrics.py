from __future__ import annotations

import asyncio
import hashlib

from backend.app.evaluation.adapter import EvaluationExecutionContext
from backend.app.evaluation.adapters import RetrievalEvaluationAdapter
from backend.app.evaluation.artifact_resolver import ControlledArtifactResolver, EvaluationAccessContext
from backend.app.evaluation.graph import EvaluationGraph
from backend.app.evaluation.mock_runner import build_synthetic_suite
from backend.app.evaluation.schemas import EvaluationArtifactRef, RetrievalOutcome


def test_six_component_deterministic_suite_runs_without_network():
    suite = build_synthetic_suite()
    run = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    completed = asyncio.run(suite.service.process_run(run.run_id))
    assert completed.status == "completed"
    assert completed.complete
    results = suite.store.list_case_results(run.run_id)
    assert {item.component for item in results} == {
        "index", "retrieval", "agent", "alignment", "answer", "observability"
    }
    assert all(item.evaluation_outcome == "passed" for item in results)


def test_evaluation_graph_is_independent_orchestration_boundary():
    suite = build_synthetic_suite()
    run = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    graph = EvaluationGraph(suite.service)

    completed = asyncio.run(graph.invoke(run.run_id))

    assert completed.status == "completed"
    assert "adapter_execution" in graph.stage_order


def test_completed_case_can_fail_quality_gold():
    suite = build_synthetic_suite()
    case = suite.store.cases["synthetic-retrieval-001"]
    context = EvaluationExecutionContext(
        evaluation_run_id="run-quality-failure",
        resolver=ControlledArtifactResolver(),
        access_context=EvaluationAccessContext("test", local_admin=True),
        fixed_outcomes={
            case.case_id: RetrievalOutcome(
                ranked_entity_ids=[], ranked_chunk_ids=[], channel_status={}
            )
        },
    )
    result = asyncio.run(RetrievalEvaluationAdapter().execute(case, context))
    assert result.execution_status == "completed"
    assert result.evaluation_outcome == "failed"
    assert result.quality_failure_codes


def test_execution_error_is_not_quality_failure():
    suite = build_synthetic_suite()
    case = suite.store.cases["synthetic-retrieval-001"]

    def fail(_case):
        raise RuntimeError("fixture executor failed")

    context = EvaluationExecutionContext(
        evaluation_run_id="run-execution-error",
        resolver=ControlledArtifactResolver(),
        access_context=EvaluationAccessContext("test", local_admin=True),
        executors={"retrieval": fail},
    )
    result = asyncio.run(RetrievalEvaluationAdapter().execute(case, context))
    assert result.execution_status == "error"
    assert result.evaluation_outcome is None
    assert not result.quality_failure_codes


def test_not_evaluable_component_is_not_failed():
    suite = build_synthetic_suite()
    case = suite.store.cases["synthetic-retrieval-001"]
    context = EvaluationExecutionContext(
        evaluation_run_id="run-not-evaluable",
        resolver=ControlledArtifactResolver(),
        access_context=EvaluationAccessContext("test", local_admin=True),
    )
    result = asyncio.run(RetrievalEvaluationAdapter().execute(case, context))
    assert result.execution_status == "completed"
    assert result.evaluation_outcome == "not_evaluable"


def test_metric_engine_reports_retrieval_and_alignment_metrics():
    suite = build_synthetic_suite()
    run = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    asyncio.run(suite.service.process_run(run.run_id))
    definitions = suite.store.metric_definitions
    names = {
        definitions[item.metric_definition_id].name
        for item in suite.store.list_metric_results(run.run_id)
    }
    assert {"recall_at_20", "mrr", "ndcg_at_10", "pair_f1", "brier", "ece"} <= names


def test_running_evaluation_recovers_without_duplicating_completed_case():
    suite = build_synthetic_suite()
    run = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    run = run.model_copy(update={"status": "preparing"})
    suite.store.update_run(run)
    run = run.model_copy(update={"status": "running"})
    suite.store.update_run(run)
    case = suite.store.cases["synthetic-retrieval-001"]
    context = suite.service._context(run, [case])  # noqa: SLF001 - recovery fixture
    first = asyncio.run(RetrievalEvaluationAdapter().execute(case, context))
    suite.store.save_case_result(first)
    completed = asyncio.run(suite.service.process_run(run.run_id))
    assert completed.status == "completed"
    results = suite.store.list_case_results(run.run_id)
    assert len(results) == 6
    assert len({item.result_id for item in results}) == 6


def test_reference_and_candidate_index_are_separate():
    suite = build_synthetic_suite()
    case = suite.store.cases["synthetic-index-001"]
    outcome = suite.outcomes[case.case_id]
    assert case.fixture.reference_index_version_id == "index-reference-v1"
    assert outcome.candidate_index_version_id == "candidate-index-isolated-v1"  # type: ignore[union-attr]
    assert outcome.candidate_index_version_id != case.fixture.reference_index_version_id  # type: ignore[union-attr]


def test_offline_recompute_reads_hash_verified_prediction_artifact(tmp_path):
    suite = build_synthetic_suite()
    case = suite.store.cases["synthetic-retrieval-001"]
    outcome = suite.outcomes[case.case_id]
    content = outcome.model_dump_json().encode()  # type: ignore[union-attr]
    (tmp_path / "prediction.json").write_bytes(content)
    artifact = EvaluationArtifactRef(
        artifact_ref_id="prediction-ref",
        artifact_type="prediction",
        artifact_id="prediction",
        content_hash=hashlib.sha256(content).hexdigest(),
        authority="derived_result",
        storage_kind="filesystem_fixture",
        storage_locator="fixture:prediction.json",
        media_type="application/json",
        size_bytes=len(content),
        redaction_policy="fixture",
        availability_status="available",
    )
    context = EvaluationExecutionContext(
        evaluation_run_id="offline-run",
        resolver=ControlledArtifactResolver(fixture_root=tmp_path),
        access_context=EvaluationAccessContext("test", local_admin=True),
        artifact_refs={artifact.artifact_ref_id: artifact},
    )
    offline_case = case.model_copy(update={"input_artifact_ref_ids": [artifact.artifact_ref_id]})
    result = asyncio.run(RetrievalEvaluationAdapter().execute(offline_case, context))
    assert result.evaluation_outcome == "passed"


def test_artifact_hash_mismatch_marks_result_incomplete(tmp_path):
    suite = build_synthetic_suite()
    case = suite.store.cases["synthetic-retrieval-001"]
    (tmp_path / "prediction.json").write_text("{}", encoding="utf-8")
    artifact = EvaluationArtifactRef(
        artifact_ref_id="prediction-ref",
        artifact_type="prediction",
        artifact_id="prediction",
        content_hash="0" * 64,
        authority="derived_result",
        storage_kind="filesystem_fixture",
        storage_locator="fixture:prediction.json",
        media_type="application/json",
        redaction_policy="fixture",
        availability_status="available",
    )
    context = EvaluationExecutionContext(
        evaluation_run_id="offline-run",
        resolver=ControlledArtifactResolver(fixture_root=tmp_path),
        access_context=EvaluationAccessContext("test", local_admin=True),
        artifact_refs={artifact.artifact_ref_id: artifact},
    )
    result = asyncio.run(
        RetrievalEvaluationAdapter().execute(
            case.model_copy(update={"input_artifact_ref_ids": [artifact.artifact_ref_id]}), context
        )
    )
    assert result.evaluation_outcome == "indeterminate"
    assert not result.complete
    assert "artifact_hash_mismatch" in result.incomplete_reason_codes
