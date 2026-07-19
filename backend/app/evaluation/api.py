from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from backend.app.evaluation.access_policy import (
    EvaluationCallerIdentity,
    LocalAdminEvaluationAccessPolicy,
)
from backend.app.evaluation.bad_case_service import BadCaseService
from backend.app.evaluation.baseline_service import BaselineService
from backend.app.evaluation.comparator import compare_runs
from backend.app.evaluation.evaluation_service import EvaluationService
from backend.app.evaluation.promotion_service import PromotionService
from backend.app.evaluation.regression_gate import RegressionGateEngine
from backend.app.evaluation.schemas import (
    BadCaseTransitionRequest,
    BaselinePromotionRequest,
    ComparisonCreateRequest,
    EvaluationRunCreateRequest,
    RegressionPromotionRequest,
)
from backend.app.evaluation.stable_ids import stable_hash
from backend.app.evaluation.store_protocol import EvaluationStoreError
from backend.app.observability.context import current_trace_context
from backend.app.persistence.evaluation_store import EvaluationStore
from backend.app.services.evaluation_run_coordinator import EvaluationRunCoordinator
from backend.app.services.observability_runtime import get_observability_runtime


router = APIRouter(prefix="/evaluations", tags=["evaluation"])
bad_case_router = APIRouter(prefix="/bad-cases", tags=["evaluation-bad-cases"])
catalog_router = APIRouter(prefix="/evaluation", tags=["evaluation-datasets"])
_coordinator: EvaluationRunCoordinator | None = None
_policy = LocalAdminEvaluationAccessPolicy()


@lru_cache(maxsize=1)
def get_evaluation_store() -> EvaluationStore:
    return EvaluationStore(os.getenv("EVALUATION_DB_PATH", "data/evaluation.sqlite3"))


@lru_cache(maxsize=1)
def get_evaluation_service() -> EvaluationService:
    return EvaluationService(
        get_evaluation_store(),
        fixture_root=os.getenv("EVALUATION_FIXTURE_ROOT", "evaluation"),
    )


async def start_evaluation_runtime() -> None:
    global _coordinator
    if not _enabled() or _coordinator is not None:
        return
    coordinator = EvaluationRunCoordinator(
        store=get_evaluation_store(),
        service=get_evaluation_service(),
        max_concurrent_runs=int(os.getenv("EVALUATION_MAX_CONCURRENT_RUNS", "1")),
        lease_seconds=int(os.getenv("EVALUATION_LEASE_SECONDS", "60")),
    )
    await coordinator.start()
    _coordinator = coordinator


async def stop_evaluation_runtime() -> None:
    global _coordinator
    if _coordinator is not None:
        await _coordinator.stop()
    _coordinator = None


@router.post("/runs", status_code=202)
def create_evaluation_run(
    payload: EvaluationRunCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    caller = _caller(request)
    if not _policy.can_create_run(caller):
        return _not_found()
    if payload.mode == "live_experiment":
        if not _live_enabled():
            return _error("evaluation_live_disabled", status=503)
        if not _policy.can_run_live_experiment(caller):
            return _not_found()
        if not get_evaluation_service().live_executor_configured:
            return _error("evaluation_live_executor_unavailable", status=503)
    try:
        store = get_evaluation_store()
        scope_hash = _scope_hash(caller)
        request_hash = stable_hash(payload.model_dump(mode="json"))
        if idempotency_key:
            existing = store.resolve_idempotency(
                caller_scope_hash=scope_hash,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if existing is not None:
                trials = (
                    store.list_trial_runs(existing.trial_group_id)
                    if existing.trial_group_id else [existing]
                )
                return {"run": existing, "runs": trials, "reused": True}
        runs = [
            get_evaluation_service().prepare_run(
                payload,
                caller_scope_hash=scope_hash,
                repeat_index=index if payload.live_trial is not None else None,
            )
            for index in range(payload.live_trial.repeat_count if payload.live_trial else 1)
        ]
        run = runs[0]
        if idempotency_key:
            store.save_idempotency(
                caller_scope_hash=scope_hash,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                run_id=run.run_id,
            )
        context = current_trace_context()
        if context is not None:
            for trial_run in runs:
                get_observability_runtime().register_enqueue_link(
                    trial_run.run_id, context.trace_id, context.span_id
                )
        if _coordinator is not None:
            _coordinator.notify()
        return {"run": run, "runs": runs, "reused": False}
    except EvaluationStoreError as exc:
        return _store_error(exc)


@router.get("/runs/{run_id}")
def get_evaluation_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    result = _authorized_run(run_id, request)
    return result


@router.get("/runs")
def list_evaluation_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    caller = _caller(request)
    if not _policy.can_create_run(caller):
        return _not_found()
    items = get_evaluation_store().list_runs(limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_evaluation_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    authorized = _authorized_run(run_id, request)
    if isinstance(authorized, JSONResponse):
        return authorized
    try:
        run = get_evaluation_store().request_cancel(run_id)
        if _coordinator is not None:
            _coordinator.notify()
        return run
    except EvaluationStoreError as exc:
        return _store_error(exc)


@router.get("/runs/{run_id}/results")
def get_evaluation_results(
    run_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    authorized = _authorized_run(run_id, request)
    if isinstance(authorized, JSONResponse):
        return authorized
    rows = get_evaluation_store().list_case_results(run_id)
    return {"items": rows[offset : offset + limit], "total": len(rows), "limit": limit, "offset": offset}


@router.get("/runs/{run_id}/metrics")
def get_evaluation_metrics(run_id: str, request: Request):
    authorized = _authorized_run(run_id, request)
    if isinstance(authorized, JSONResponse):
        return authorized
    return {"items": get_evaluation_store().list_metric_results(run_id)}


@router.post("/comparisons")
def create_comparison(payload: ComparisonCreateRequest, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    caller = _caller(request)
    try:
        store = get_evaluation_store()
        binding = store.get_baseline_binding(payload.baseline_binding_id)
        baseline = store.get_run(binding.baseline_run_id)
        candidate = store.get_run(payload.candidate_run_id)
        if not (_policy.can_read_run(caller, baseline) and _policy.can_read_run(caller, candidate)):
            return _not_found()
        baseline_metrics = store.list_metric_results(baseline.run_id)
        candidate_metrics = store.list_metric_results(candidate.run_id)
        metric_ids = {
            item.metric_definition_id for item in baseline_metrics + candidate_metrics
        }
        comparison = compare_runs(
            baseline_run=baseline,
            candidate_run=candidate,
            baseline_environment=store.get_environment(baseline.environment_id),
            candidate_environment=store.get_environment(candidate.environment_id),
            baseline_case_results=store.list_case_results(baseline.run_id),
            candidate_case_results=store.list_case_results(candidate.run_id),
            baseline_metrics=baseline_metrics,
            candidate_metrics=candidate_metrics,
            metric_names={
                metric_id: store.get_metric_definition(metric_id).name for metric_id in metric_ids
            },
            baseline_binding_id=binding.baseline_binding_id,
        )
        store.save_comparison(comparison)
        gate = None
        if comparison.status == "ready":
            config = store.get_gate_config(binding.gate_config_version)
            gate = RegressionGateEngine().evaluate(comparison, config)
            store.save_gate(gate)
        return {"comparison": comparison, "gate": gate}
    except EvaluationStoreError as exc:
        return _store_error(exc)


@router.get("/comparisons")
def list_comparisons(request: Request, limit: int = Query(default=100, ge=1, le=500)):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_create_run(_caller(request)):
        return _not_found()
    return {"items": get_evaluation_store().list_comparisons(limit=limit)}


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        comparison = get_evaluation_store().get_comparison(comparison_id)
        candidate = get_evaluation_store().get_run(comparison.candidate_run_id)
        if not _policy.can_read_run(_caller(request), candidate):
            return _not_found()
        return comparison
    except EvaluationStoreError:
        return _not_found()


@router.post("/baselines")
def promote_baseline(payload: BaselinePromotionRequest, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    caller = _caller(request)
    if not _policy.can_manage_baseline(caller):
        return _not_found()
    try:
        store = get_evaluation_store()
        return BaselineService(store).promote(
            dataset_version_id=payload.dataset_version_id,
            component=payload.component,
            evaluation_mode=payload.evaluation_mode,
            gate_config=store.get_gate_config(payload.gate_config_version),
            baseline_run_id=payload.baseline_run_id,
            promoted_by_scope=caller.subject,
            promotion_reason_code=payload.promotion_reason_code,
        )
    except EvaluationStoreError as exc:
        return _store_error(exc)


@router.get("/baselines")
def list_baselines(request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_manage_baseline(_caller(request)):
        return _not_found()
    return {"items": get_evaluation_store().list_baseline_bindings()}


@catalog_router.get("/datasets")
def list_datasets(request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_create_run(_caller(request)):
        return _not_found()
    return {"items": get_evaluation_store().list_datasets()}


@catalog_router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_create_run(_caller(request)):
        return _not_found()
    try:
        store = get_evaluation_store()
        return {
            "dataset": store.get_dataset(dataset_id),
            "versions": store.list_dataset_versions(dataset_id),
        }
    except EvaluationStoreError:
        return _not_found()


@bad_case_router.get("")
def list_bad_cases(
    request: Request,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_manage_bad_cases(_caller(request)):
        return _not_found()
    rows = get_evaluation_store().list_bad_cases(status=status)
    return {"items": rows[offset : offset + limit], "total": len(rows)}


@bad_case_router.get("/{bad_case_id}")
def get_bad_case(bad_case_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_manage_bad_cases(_caller(request)):
        return _not_found()
    try:
        store = get_evaluation_store()
        return {
            "bad_case": store.get_bad_case(bad_case_id),
            "occurrences": store.list_bad_case_occurrences(bad_case_id),
            "events": store.list_bad_case_events(bad_case_id),
        }
    except EvaluationStoreError:
        return _not_found()


def _transition_bad_case(
    bad_case_id: str, target: str, payload: BadCaseTransitionRequest, request: Request
):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    caller = _caller(request)
    if not _policy.can_manage_bad_cases(caller):
        return _not_found()
    try:
        return BadCaseService(get_evaluation_store()).transition(
            bad_case_id, target, payload, actor_scope=caller.subject
        )
    except EvaluationStoreError as exc:
        return _store_error(exc)


@bad_case_router.post("/{bad_case_id}/triage")
def triage_bad_case(bad_case_id: str, payload: BadCaseTransitionRequest, request: Request):
    return _transition_bad_case(bad_case_id, "triaged", payload, request)


@bad_case_router.post("/{bad_case_id}/confirm")
def confirm_bad_case(bad_case_id: str, payload: BadCaseTransitionRequest, request: Request):
    return _transition_bad_case(bad_case_id, "confirmed", payload, request)


@bad_case_router.post("/{bad_case_id}/mark-fixed")
def mark_bad_case_fixed(bad_case_id: str, payload: BadCaseTransitionRequest, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_manage_bad_cases(_caller(request)):
        return _not_found()
    service = BadCaseService(get_evaluation_store())
    try:
        current = get_evaluation_store().get_bad_case(bad_case_id)
        if current.status == "confirmed":
            current = service.transition(
                bad_case_id,
                "fixing",
                payload,
                actor_scope=_caller(request).subject,
            )
            payload = payload.model_copy(update={"based_on_revision": current.revision})
    except EvaluationStoreError as exc:
        return _store_error(exc)
    return _transition_bad_case(bad_case_id, "fixed", payload, request)


@bad_case_router.post("/{bad_case_id}/verify")
def verify_bad_case(bad_case_id: str, payload: BadCaseTransitionRequest, request: Request):
    return _transition_bad_case(bad_case_id, "verified", payload, request)


@bad_case_router.post("/{bad_case_id}/promote")
def promote_bad_case(bad_case_id: str, payload: RegressionPromotionRequest, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    if not _policy.can_manage_bad_cases(_caller(request)):
        return _not_found()
    try:
        return PromotionService(get_evaluation_store()).promote(
            bad_case_id=bad_case_id,
            source_dataset_version_id=payload.source_dataset_version_id,
            target_dataset_version_id=payload.target_dataset_version_id,
            new_case_id=payload.new_case_id,
            source_trace_id=payload.source_trace_id,
            pre_fix_reproduction_result_id=payload.pre_fix_reproduction_result_id,
            reproduced=payload.reproduced,
            fix_reference=payload.fix_reference,
            regression_case=payload.regression_case,
        )
    except EvaluationStoreError as exc:
        return _store_error(exc)


def _authorized_run(run_id: str, request: Request):
    unavailable = _unavailable()
    if unavailable:
        return unavailable
    try:
        run = get_evaluation_store().get_run(run_id)
    except EvaluationStoreError:
        return _not_found()
    if not _policy.can_read_run(_caller(request), run):
        return _not_found()
    return run


def _caller(request: Request) -> EvaluationCallerIdentity:
    host = request.client.host if request.client else "unknown"
    if host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return EvaluationCallerIdentity(identity_type="local_admin", subject="local-admin")
    return EvaluationCallerIdentity(identity_type="anonymous", subject="anonymous")


def _scope_hash(caller: EvaluationCallerIdentity) -> str:
    return stable_hash([caller.identity_type, caller.subject])


def _enabled() -> bool:
    return os.getenv("EVALUATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _api_enabled() -> bool:
    return os.getenv("EVALUATION_API_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _live_enabled() -> bool:
    return os.getenv("EVALUATION_LIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _unavailable() -> JSONResponse | None:
    if not _api_enabled():
        return _error("evaluation_api_disabled", status=503)
    if not _enabled():
        return _error("evaluation_disabled", status=503)
    return None


def _not_found() -> JSONResponse:
    return _error("evaluation_not_found", status=404)


def _store_error(exc: EvaluationStoreError) -> JSONResponse:
    status = 404 if exc.error_code.endswith("not_found") else (
        409 if any(term in exc.error_code for term in ("conflict", "immutable", "not_allowed")) else 400
    )
    return _error(exc.error_code, status=status, retryable=exc.retryable)


def _error(error_code: str, *, status: int = 400, retryable: bool = False) -> JSONResponse:
    context = current_trace_context()
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "error_code": error_code,
                "component": "evaluation",
                "message": error_code.replace("_", " "),
                "retryable": retryable,
                "context": {},
                "trace_id": context.trace_id if context else None,
            }
        },
    )
