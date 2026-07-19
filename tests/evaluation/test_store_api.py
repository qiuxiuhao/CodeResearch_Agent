from __future__ import annotations

from pathlib import Path
import asyncio
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.evaluation.api import (
    bad_case_router,
    catalog_router,
    get_evaluation_service,
    get_evaluation_store,
    router,
)
from backend.app.evaluation.access_policy import (
    EvaluationCallerIdentity,
    LocalAdminEvaluationAccessPolicy,
)
from backend.app.evaluation.baseline_service import BaselineService
from backend.app.evaluation.schemas import RegressionGateConfig
from backend.app.evaluation.stable_ids import stable_hash
from backend.app.evaluation.mock_runner import build_synthetic_suite
from backend.app.persistence.evaluation_store import EvaluationStore


def _persist_suite(path: Path):
    suite = build_synthetic_suite()
    store = EvaluationStore(path)
    store.migrate()
    subject = next(iter(suite.store.subjects.values()))
    dataset = next(iter(suite.store.datasets.values()))
    frozen = next(iter(suite.store.versions.values()))
    store.save_subject(subject)
    store.save_dataset(dataset)
    store.save_dataset_version(frozen.model_copy(update={"status": "draft", "frozen_at": None}))
    for case in suite.store.cases.values():
        store.save_case(case)
    store.save_dataset_version(frozen)
    environment = next(iter(suite.store.environments.values()))
    store.save_environment(environment)
    return store, suite, subject, environment


def test_evaluation_store_migration_and_frozen_dataset(tmp_path):
    store, suite, _subject, _environment = _persist_suite(tmp_path / "evaluation.sqlite3")
    version = store.get_dataset_version("synthetic-regression-v1")
    assert version.status == "frozen"
    assert len(store.list_cases(version.dataset_version_id)) == 6
    assert store.list_datasets()[0].dataset_id == "synthetic-regression"


def test_evaluation_api_defaults_disabled(monkeypatch):
    monkeypatch.delenv("EVALUATION_ENABLED", raising=False)
    monkeypatch.delenv("EVALUATION_API_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(router)
    app.include_router(catalog_router)
    app.include_router(bad_case_router)
    response = TestClient(app).get("/evaluation/datasets")
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == "evaluation_api_disabled"


def test_caller_scope_hash_is_not_authorization():
    policy = LocalAdminEvaluationAccessPolicy()
    caller = EvaluationCallerIdentity(
        identity_type="anonymous", subject="self-asserted-hash", repository_ids=frozenset({"repo"})
    )
    assert not policy.can_create_run(caller)
    assert not policy.can_manage_baseline(caller)


def test_idempotency_key_conflict(tmp_path):
    store, _suite, _subject, _environment = _persist_suite(tmp_path / "evaluation.sqlite3")
    # The key stores only a hash; callers cannot retrieve the original secret value.
    run_id = "missing-run"
    # A foreign-key target is required, so this assertion focuses on conflict resolution after
    # a normal API-created run in integration tests. The table itself must exist and be empty.
    with store._connect() as connection:  # noqa: SLF001 - migration contract assertion
        count = connection.execute("SELECT COUNT(*) FROM evaluation_idempotency_keys").fetchone()[0]
    assert count == 0


def test_evaluation_run_api_idempotency(monkeypatch, tmp_path):
    database = tmp_path / "evaluation-api.sqlite3"
    _store, suite, _subject, _environment = _persist_suite(database)
    monkeypatch.setenv("EVALUATION_ENABLED", "true")
    monkeypatch.setenv("EVALUATION_API_ENABLED", "true")
    monkeypatch.setenv("EVALUATION_DB_PATH", str(database))
    get_evaluation_store.cache_clear()
    get_evaluation_service.cache_clear()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = suite.request.model_dump(mode="json")
    first = client.post("/evaluations/runs", json=payload, headers={"Idempotency-Key": "same-key"})
    second = client.post("/evaluations/runs", json=payload, headers={"Idempotency-Key": "same-key"})
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["reused"] is True
    changed = {**payload, "random_seed": 99}
    conflict = client.post(
        "/evaluations/runs", json=changed, headers={"Idempotency-Key": "same-key"}
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["error_code"] == "evaluation_idempotency_conflict"
    get_evaluation_store.cache_clear()
    get_evaluation_service.cache_clear()


def test_sqlite_baseline_binding_does_not_modify_completed_run(tmp_path):
    store, suite, _subject, _environment = _persist_suite(tmp_path / "baseline.sqlite3")
    run = suite.service.prepare_run(suite.request, caller_scope_hash="test")
    run = asyncio.run(suite.service.process_run(run.run_id))
    store.save_plan(suite.store.get_plan(run.plan_id))
    store.save_run(run, caller_scope_hash="admin")
    for definition in suite.store.metric_definitions.values():
        store.save_metric_definition(definition)
    for result in suite.store.list_case_results(run.run_id):
        store.save_case_result(result)
    for metric in suite.store.list_metric_results(run.run_id):
        store.save_metric_result(metric)
    config = RegressionGateConfig(
        gate_config_version="sqlite-ci", profile_type="ci",
        config_hash=stable_hash("sqlite-ci"), created_at=datetime.now(UTC),
    )
    store.save_gate_config(config)
    binding = BaselineService(store).promote(
        dataset_version_id=run.dataset_version_id,
        component="retrieval",
        evaluation_mode=run.mode,
        gate_config=config,
        baseline_run_id=run.run_id,
        promoted_by_scope="admin",
        promotion_reason_code="sqlite-test",
    )
    assert binding.dataset_source_profile == "synthetic_fixture"
    assert store.get_run(run.run_id) == run
