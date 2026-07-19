from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from backend.app.evaluation.schemas import (
    BadCase,
    BadCaseEvent,
    BadCaseOccurrence,
    BadCaseVerification,
    CaseResult,
    EvaluationBaselineBinding,
    EvaluationArtifactRef,
    EvaluationCase,
    EvaluationDataset,
    EvaluationDatasetVersion,
    EvaluationPlan,
    EvaluationRun,
    EvaluationSubject,
    ExecutionEnvironment,
    MetricDefinition,
    MetricResult,
    RegressionCasePromotion,
    RegressionComparison,
    RegressionGate,
    RegressionGateConfig,
    ReplayManifest,
)
from backend.app.evaluation.store_protocol import EvaluationStoreError
from backend.app.evaluation.subjects import (
    EvaluationSubjectError,
    require_formal_baseline_subject,
    validate_subject_hash,
)


MIGRATIONS_DIR = Path(__file__).with_name("evaluation_migrations")
SCHEMA_VERSION = 1
TERMINAL_RUN_STATUSES = {"completed", "partial", "failed", "cancelled"}
CLAIMABLE_RUN_STATUSES = {"queued", "preparing", "running", "aggregating", "comparing"}
RUN_TRANSITIONS = {
    "queued": {"preparing", "failed", "cancelled"},
    "preparing": {"running", "failed", "cancelled"},
    "running": {"aggregating", "failed", "cancelled"},
    "aggregating": {"comparing", "completed", "partial", "failed", "cancelled"},
    "comparing": {"completed", "partial", "failed", "cancelled"},
}


@dataclass(frozen=True, slots=True)
class EvaluationLease:
    run_id: str
    owner: str
    token: str
    expires_at: datetime


class EvaluationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise EvaluationStoreError("evaluation_schema_too_new", str(current))
            for version in range(current + 1, SCHEMA_VERSION + 1):
                path = MIGRATIONS_DIR / f"{version:03d}_evaluation.sql"
                if not path.is_file():
                    raise EvaluationStoreError("evaluation_migration_missing", path.name)
                connection.executescript(path.read_text(encoding="utf-8"))

    def save_subject(self, subject: EvaluationSubject) -> None:
        try:
            validate_subject_hash(subject)
        except EvaluationSubjectError as exc:
            raise EvaluationStoreError(str(exc)) from exc
        self._immutable_json(
            "evaluation_subjects", "subject_id", subject.subject_id, "subject_json", subject,
            ("subject_hash", "subject_type", "created_at"),
            (subject.subject_hash, subject.subject_type, _iso(subject.created_at)),
            "evaluation_subject_immutable",
        )

    def get_subject(self, subject_id: str) -> EvaluationSubject:
        return self._get_model(
            "evaluation_subjects", "subject_id", subject_id, "subject_json", EvaluationSubject,
            "evaluation_subject_not_found",
        )

    def save_artifact_ref(self, artifact_ref: EvaluationArtifactRef) -> None:
        self._immutable_json(
            "evaluation_artifact_refs", "artifact_ref_id", artifact_ref.artifact_ref_id,
            "artifact_json", artifact_ref,
            ("artifact_id", "content_hash", "storage_kind"),
            (artifact_ref.artifact_id, artifact_ref.content_hash, artifact_ref.storage_kind),
            "evaluation_artifact_ref_immutable",
        )

    def get_artifact_ref(self, artifact_ref_id: str) -> EvaluationArtifactRef:
        return self._get_model(
            "evaluation_artifact_refs", "artifact_ref_id", artifact_ref_id,
            "artifact_json", EvaluationArtifactRef, "evaluation_artifact_not_found",
        )

    def save_dataset(self, dataset: EvaluationDataset) -> None:
        self._upsert_draft(
            "evaluation_datasets", "dataset_id", dataset.dataset_id, "dataset_json", dataset,
            ("dataset_family_id", "status", "created_at", "updated_at"),
            (dataset.dataset_family_id, dataset.status, _iso(dataset.created_at), _iso(dataset.updated_at)),
            terminal=dataset.status != "draft",
        )

    def get_dataset(self, dataset_id: str) -> EvaluationDataset:
        return self._get_model(
            "evaluation_datasets", "dataset_id", dataset_id, "dataset_json",
            EvaluationDataset, "evaluation_dataset_not_found",
        )

    def list_datasets(self) -> list[EvaluationDataset]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT dataset_json FROM evaluation_datasets ORDER BY updated_at DESC"
            ).fetchall()
        return [EvaluationDataset.model_validate_json(row[0]) for row in rows]

    def save_dataset_version(self, version: EvaluationDatasetVersion) -> None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status,version_json FROM evaluation_dataset_versions WHERE dataset_version_id=?",
                (version.dataset_version_id,),
            ).fetchone()
            if row and row["status"] == "frozen" and row["version_json"] != _model_json(version):
                raise EvaluationStoreError("evaluation_dataset_version_frozen")
            connection.execute(
                """INSERT INTO evaluation_dataset_versions(
                       dataset_version_id,dataset_id,status,content_hash,version_json,created_at,frozen_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(dataset_version_id) DO UPDATE SET
                     status=excluded.status,content_hash=excluded.content_hash,
                     version_json=excluded.version_json,frozen_at=excluded.frozen_at
                   WHERE evaluation_dataset_versions.status IN ('draft','validating')""",
                (
                    version.dataset_version_id, version.dataset_id, version.status, version.content_hash,
                    _model_json(version), _iso(version.created_at), _iso(version.frozen_at),
                ),
            )

    def get_dataset_version(self, version_id: str) -> EvaluationDatasetVersion:
        return self._get_model(
            "evaluation_dataset_versions", "dataset_version_id", version_id, "version_json",
            EvaluationDatasetVersion, "evaluation_dataset_version_not_found",
        )

    def list_dataset_versions(self, dataset_id: str) -> list[EvaluationDatasetVersion]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT version_json FROM evaluation_dataset_versions WHERE dataset_id=? ORDER BY created_at DESC",
                (dataset_id,),
            ).fetchall()
        return [EvaluationDatasetVersion.model_validate_json(row[0]) for row in rows]

    def save_case(self, case: EvaluationCase) -> None:
        version = self.get_dataset_version(case.dataset_version_id)
        self.migrate()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT case_json FROM evaluation_cases WHERE case_id=?", (case.case_id,)
            ).fetchone()
            if version.status == "frozen" and existing is None:
                raise EvaluationStoreError("evaluation_dataset_version_frozen")
            if existing and existing["case_json"] != _model_json(case):
                raise EvaluationStoreError("evaluation_case_immutable")
            connection.execute(
                """INSERT OR IGNORE INTO evaluation_cases(
                   case_id,stable_case_family_id,dataset_version_id,component,split,source,
                   repo_id,content_hash,case_json) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    case.case_id, case.stable_case_family_id, case.dataset_version_id,
                    case.component, case.split, case.source, case.repo_id, case.content_hash,
                    _model_json(case),
                ),
            )

    def list_cases(self, version_id: str, case_ids: list[str] | None = None) -> list[EvaluationCase]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT case_json FROM evaluation_cases WHERE dataset_version_id=? ORDER BY case_id",
                (version_id,),
            ).fetchall()
        items = [EvaluationCase.model_validate_json(row["case_json"]) for row in rows]
        if case_ids:
            requested = set(case_ids)
            items = [item for item in items if item.case_id in requested]
            if {item.case_id for item in items} != requested:
                raise EvaluationStoreError("evaluation_case_not_found")
        return items

    def save_environment(self, environment: ExecutionEnvironment) -> None:
        self._immutable_json(
            "evaluation_execution_environments", "environment_id", environment.environment_id,
            "environment_json", environment, ("environment_hash",), (environment.environment_hash,),
            "evaluation_environment_immutable",
        )

    def get_environment(self, environment_id: str) -> ExecutionEnvironment:
        return self._get_model(
            "evaluation_execution_environments", "environment_id", environment_id,
            "environment_json", ExecutionEnvironment, "evaluation_environment_not_found",
        )

    def save_plan(self, plan: EvaluationPlan) -> None:
        self._immutable_json(
            "evaluation_plans", "plan_id", plan.plan_id, "plan_json", plan,
            ("dataset_version_id", "subject_id", "mode"),
            (plan.dataset_version_id, plan.subject_id, plan.mode), "evaluation_plan_immutable",
        )

    def get_plan(self, plan_id: str) -> EvaluationPlan:
        return self._get_model(
            "evaluation_plans", "plan_id", plan_id, "plan_json", EvaluationPlan,
            "evaluation_plan_not_found",
        )

    def save_run(self, run: EvaluationRun, *, caller_scope_hash: str = "") -> None:
        self.migrate()
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO evaluation_runs(
                       run_id,plan_id,dataset_version_id,subject_id,environment_id,mode,status,
                       run_fingerprint_hash,attempt_number,retry_of_run_id,cancel_requested,
                       caller_scope_hash,run_json,created_at,updated_at,finished_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run.run_id, run.plan_id, run.dataset_version_id, run.subject_id,
                        run.environment_id, run.mode, run.status,
                        run.run_fingerprint.run_fingerprint_hash, run.attempt_number,
                        run.retry_of_run_id, int(run.cancel_requested), caller_scope_hash,
                        _model_json(run), _iso(run.created_at), _iso(run.updated_at), _iso(run.finished_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.get_run(run.run_id)
                if existing != run:
                    raise EvaluationStoreError("evaluation_run_conflict", str(exc)) from exc

    def get_run(self, run_id: str) -> EvaluationRun:
        return self._get_model(
            "evaluation_runs", "run_id", run_id, "run_json", EvaluationRun,
            "evaluation_run_not_found",
        )

    def find_reusable_run(self, run_fingerprint_hash: str) -> EvaluationRun | None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT run_json FROM evaluation_runs
                   WHERE run_fingerprint_hash=?
                     AND status IN ('queued','preparing','running','aggregating','comparing','completed')
                   ORDER BY attempt_number DESC,created_at DESC LIMIT 1""",
                (run_fingerprint_hash,),
            ).fetchone()
        return EvaluationRun.model_validate_json(row[0]) if row else None

    def get_run_for_caller(self, run_id: str, caller_scope_hash: str) -> EvaluationRun:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT caller_scope_hash,run_json FROM evaluation_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None or row["caller_scope_hash"] != caller_scope_hash:
            raise EvaluationStoreError("evaluation_run_not_found")
        return EvaluationRun.model_validate_json(row["run_json"])

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> list[EvaluationRun]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_json FROM evaluation_runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def resolve_idempotency(
        self, *, caller_scope_hash: str, idempotency_key: str, request_hash: str
    ) -> EvaluationRun | None:
        self.migrate()
        key_hash = _sha(idempotency_key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_hash,run_id FROM evaluation_idempotency_keys WHERE caller_scope_hash=? AND key_hash=?",
                (caller_scope_hash, key_hash),
            ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise EvaluationStoreError("evaluation_idempotency_conflict")
        return self.get_run(row["run_id"])

    def save_idempotency(
        self,
        *,
        caller_scope_hash: str,
        idempotency_key: str,
        request_hash: str,
        run_id: str,
    ) -> None:
        self.migrate()
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO evaluation_idempotency_keys(caller_scope_hash,key_hash,request_hash,run_id,created_at) VALUES(?,?,?,?,?)",
                    (caller_scope_hash, _sha(idempotency_key), request_hash, run_id, _now()),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.resolve_idempotency(
                    caller_scope_hash=caller_scope_hash,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if existing is None or existing.run_id != run_id:
                    raise EvaluationStoreError("evaluation_idempotency_conflict") from exc

    def update_run(self, run: EvaluationRun) -> None:
        current = self.get_run(run.run_id)
        if current.status in TERMINAL_RUN_STATUSES and current != run:
            raise EvaluationStoreError("evaluation_run_immutable", run.run_id)
        if run.status != current.status and run.status not in RUN_TRANSITIONS.get(current.status, set()):
            raise EvaluationStoreError(
                "evaluation_run_transition_invalid", f"{current.status}->{run.status}"
            )
        self.migrate()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE evaluation_runs SET status=?,cancel_requested=?,run_json=?,updated_at=?,finished_at=?
                   WHERE run_id=? AND status NOT IN ('completed','partial','failed','cancelled')""",
                (
                    run.status, int(run.cancel_requested), _model_json(run), _iso(run.updated_at),
                    _iso(run.finished_at), run.run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise EvaluationStoreError("evaluation_run_immutable", run.run_id)

    def request_cancel(self, run_id: str) -> EvaluationRun:
        run = self.get_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise EvaluationStoreError("evaluation_cancel_not_allowed")
        updated = run.model_copy(update={"cancel_requested": True, "updated_at": datetime.now(UTC)})
        self.update_run(updated)
        return updated

    def save_case_result(self, result: CaseResult) -> None:
        self._immutable_json(
            "evaluation_case_results", "result_id", result.result_id, "result_json", result,
            ("evaluation_run_id", "case_id", "execution_status", "evaluation_outcome", "complete"),
            (
                result.evaluation_run_id, result.case_id, result.execution_status,
                result.evaluation_outcome, int(result.complete),
            ), "evaluation_case_result_immutable",
        )

    def list_case_results(self, run_id: str) -> list[CaseResult]:
        return self._list_models(
            "evaluation_case_results", "evaluation_run_id", run_id, "result_json", CaseResult
        )

    def save_metric_definition(self, definition: MetricDefinition) -> None:
        self._immutable_json(
            "evaluation_metric_definitions", "metric_definition_id", definition.metric_definition_id,
            "definition_json", definition, ("component", "name", "version", "config_hash"),
            (definition.component, definition.name, definition.version, definition.config_hash),
            "evaluation_metric_definition_immutable",
        )

    def get_metric_definition(self, metric_definition_id: str) -> MetricDefinition:
        return self._get_model(
            "evaluation_metric_definitions", "metric_definition_id", metric_definition_id,
            "definition_json", MetricDefinition, "metric_definition_not_found",
        )

    def save_metric_result(self, result: MetricResult) -> None:
        self._immutable_json(
            "evaluation_metric_results", "metric_result_id", result.metric_result_id,
            "result_json", result, ("evaluation_run_id", "metric_definition_id", "complete"),
            (result.evaluation_run_id, result.metric_definition_id, int(result.complete)),
            "metric_result_immutable",
        )

    def list_metric_results(self, run_id: str) -> list[MetricResult]:
        return self._list_models(
            "evaluation_metric_results", "evaluation_run_id", run_id, "result_json", MetricResult
        )

    def save_comparison(self, comparison: RegressionComparison) -> None:
        self._immutable_json(
            "evaluation_comparisons", "comparison_id", comparison.comparison_id,
            "comparison_json", comparison, ("baseline_run_id", "candidate_run_id", "status"),
            (comparison.baseline_run_id, comparison.candidate_run_id, comparison.status),
            "comparison_immutable",
        )

    def get_comparison(self, comparison_id: str) -> RegressionComparison:
        return self._get_model(
            "evaluation_comparisons", "comparison_id", comparison_id, "comparison_json",
            RegressionComparison, "comparison_not_found",
        )

    def list_comparisons(self, *, limit: int = 100) -> list[RegressionComparison]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT comparison_json FROM evaluation_comparisons ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RegressionComparison.model_validate_json(row[0]) for row in rows]

    def get_gate(self, gate_id: str) -> RegressionGate:
        return self._get_model(
            "regression_gates", "gate_id", gate_id, "gate_json", RegressionGate,
            "regression_gate_not_found",
        )

    def save_gate_config(self, config: RegressionGateConfig) -> None:
        self._immutable_json(
            "regression_gate_configs", "gate_config_version", config.gate_config_version,
            "config_json", config, ("profile_type", "config_hash"),
            (config.profile_type, config.config_hash), "gate_config_immutable",
        )

    def get_gate_config(self, version: str) -> RegressionGateConfig:
        return self._get_model(
            "regression_gate_configs", "gate_config_version", version, "config_json",
            RegressionGateConfig, "gate_config_not_found",
        )

    def save_gate(self, gate: RegressionGate) -> None:
        self._immutable_json(
            "regression_gates", "gate_id", gate.gate_id, "gate_json", gate,
            ("comparison_id", "gate_config_version", "verdict"),
            (gate.comparison_id, gate.gate_config_version, gate.verdict), "regression_gate_immutable",
        )

    def promote_baseline(self, binding: EvaluationBaselineBinding) -> EvaluationBaselineBinding:
        run = self.get_run(binding.baseline_run_id)
        subject = self.get_subject(binding.subject_id)
        if run.status != "completed" or not run.complete:
            raise EvaluationStoreError("baseline_run_incomplete")
        if run.subject_id != binding.subject_id or run.dataset_version_id != binding.dataset_version_id:
            raise EvaluationStoreError("baseline_binding_identity_mismatch")
        try:
            require_formal_baseline_subject(subject)
        except EvaluationSubjectError as exc:
            raise EvaluationStoreError(str(exc)) from exc
        self.migrate()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE evaluation_baseline_bindings SET status='superseded',
                     binding_json=json_set(binding_json,'$.status','superseded')
                   WHERE dataset_version_id=? AND component=? AND evaluation_mode=?
                     AND gate_config_version=? AND status='active'""",
                (
                    binding.dataset_version_id, binding.component, binding.evaluation_mode,
                    binding.gate_config_version,
                ),
            )
            connection.execute(
                """INSERT INTO evaluation_baseline_bindings(
                   baseline_binding_id,dataset_version_id,component,evaluation_mode,
                   gate_config_version,baseline_run_id,subject_id,status,binding_json,created_at,promoted_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    binding.baseline_binding_id, binding.dataset_version_id, binding.component,
                    binding.evaluation_mode, binding.gate_config_version, binding.baseline_run_id,
                    binding.subject_id, binding.status, _model_json(binding), _iso(binding.created_at),
                    _iso(binding.promoted_at),
                ),
            )
            connection.commit()
        return binding

    def get_baseline_binding(self, binding_id: str) -> EvaluationBaselineBinding:
        return self._get_model(
            "evaluation_baseline_bindings", "baseline_binding_id", binding_id,
            "binding_json", EvaluationBaselineBinding, "evaluation_baseline_not_found",
        )

    def list_baseline_bindings(self) -> list[EvaluationBaselineBinding]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT binding_json FROM evaluation_baseline_bindings ORDER BY promoted_at DESC"
            ).fetchall()
        return [EvaluationBaselineBinding.model_validate_json(row[0]) for row in rows]

    def save_bad_case(self, bad_case: BadCase) -> None:
        self.migrate()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision,bad_case_json FROM bad_cases WHERE bad_case_id=?",
                (bad_case.bad_case_id,),
            ).fetchone()
            encoded = _model_json(bad_case)
            if row is None:
                connection.execute(
                    """INSERT INTO bad_cases(
                       bad_case_id,fingerprint,status,revision,component,case_id,bad_case_json,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        bad_case.bad_case_id, bad_case.fingerprint, bad_case.status,
                        bad_case.revision, bad_case.component, bad_case.case_id, encoded,
                        _iso(bad_case.created_at), _iso(bad_case.updated_at),
                    ),
                )
            elif row["bad_case_json"] != encoded:
                expected = int(row["revision"]) + 1
                if bad_case.revision != expected:
                    connection.rollback()
                    raise EvaluationStoreError("bad_case_conflict")
                cursor = connection.execute(
                    """UPDATE bad_cases SET status=?,revision=?,bad_case_json=?,updated_at=?
                       WHERE bad_case_id=? AND revision=?""",
                    (
                        bad_case.status, bad_case.revision, encoded, _iso(bad_case.updated_at),
                        bad_case.bad_case_id, expected - 1,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise EvaluationStoreError("bad_case_conflict")
            connection.commit()

    def get_bad_case(self, bad_case_id: str) -> BadCase:
        return self._get_model(
            "bad_cases", "bad_case_id", bad_case_id, "bad_case_json", BadCase,
            "bad_case_not_found",
        )

    def find_bad_case_by_fingerprint(self, fingerprint: str) -> BadCase | None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT bad_case_json FROM bad_cases WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
        return BadCase.model_validate_json(row[0]) if row else None

    def list_bad_cases(self, *, status: str | None = None) -> list[BadCase]:
        self.migrate()
        query = "SELECT bad_case_json FROM bad_cases"
        args: tuple = ()
        if status:
            query += " WHERE status=?"
            args = (status,)
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [BadCase.model_validate_json(row[0]) for row in rows]

    def list_bad_case_occurrences(self, bad_case_id: str) -> list[BadCaseOccurrence]:
        return self._list_models(
            "bad_case_occurrences", "bad_case_id", bad_case_id,
            "occurrence_json", BadCaseOccurrence,
        )

    def list_bad_case_events(self, bad_case_id: str) -> list[BadCaseEvent]:
        return self._list_models(
            "bad_case_events", "bad_case_id", bad_case_id, "event_json", BadCaseEvent,
        )

    def append_bad_case_occurrence(self, occurrence: BadCaseOccurrence) -> None:
        self._immutable_json(
            "bad_case_occurrences", "occurrence_id", occurrence.occurrence_id,
            "occurrence_json", occurrence,
            ("bad_case_id", "evaluation_run_id", "case_result_id", "observed_at"),
            (
                occurrence.bad_case_id, occurrence.evaluation_run_id, occurrence.case_result_id,
                _iso(occurrence.observed_at),
            ), "bad_case_occurrence_immutable",
        )

    def get_bad_case_occurrence(self, occurrence_id: str) -> BadCaseOccurrence | None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT occurrence_json FROM bad_case_occurrences WHERE occurrence_id=?",
                (occurrence_id,),
            ).fetchone()
        return BadCaseOccurrence.model_validate_json(row[0]) if row else None

    def append_bad_case_event(self, event: BadCaseEvent) -> None:
        self._immutable_json(
            "bad_case_events", "event_id", event.event_id, "event_json", event,
            ("bad_case_id", "sequence", "created_at"),
            (event.bad_case_id, event.sequence, _iso(event.created_at)), "bad_case_event_immutable",
        )

    def save_bad_case_verification(self, verification: BadCaseVerification) -> None:
        self._immutable_json(
            "bad_case_verifications", "verification_id", verification.verification_id,
            "verification_json", verification, ("bad_case_id", "verified_at"),
            (verification.bad_case_id, _iso(verification.verified_at)),
            "bad_case_verification_immutable",
        )

    def save_promotion(self, promotion: RegressionCasePromotion) -> None:
        self._immutable_json(
            "regression_case_promotions", "promotion_id", promotion.promotion_id,
            "promotion_json", promotion,
            ("bad_case_id", "target_dataset_version_id", "reproduction_status", "created_at"),
            (
                promotion.bad_case_id, promotion.target_dataset_version_id,
                promotion.reproduction_status, _iso(promotion.created_at),
            ), "promotion_immutable",
        )

    def list_promotions(self, bad_case_id: str) -> list[RegressionCasePromotion]:
        return self._list_models(
            "regression_case_promotions", "bad_case_id", bad_case_id,
            "promotion_json", RegressionCasePromotion,
        )

    def save_replay_manifest(self, manifest: ReplayManifest) -> None:
        self._immutable_json(
            "evaluation_replay_manifests", "replay_manifest_id", manifest.replay_manifest_id,
            "manifest_json", manifest,
            ("source_evaluation_run_id", "readiness"),
            (manifest.source_evaluation_run_id, manifest.readiness),
            "replay_manifest_immutable",
        )

    def get_replay_manifest(self, replay_manifest_id: str) -> ReplayManifest:
        return self._get_model(
            "evaluation_replay_manifests", "replay_manifest_id", replay_manifest_id,
            "manifest_json", ReplayManifest, "replay_manifest_not_found",
        )

    def list_claimable_runs(self, limit: int = 20) -> list[EvaluationRun]:
        self.migrate()
        now = _now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT r.run_json FROM evaluation_runs r
                   LEFT JOIN evaluation_run_leases l ON l.run_id=r.run_id
                   WHERE r.status IN ('queued','preparing','running','aggregating','comparing')
                     AND (l.run_id IS NULL OR l.expires_at<=?)
                   ORDER BY r.created_at LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def list_trial_runs(self, trial_group_id: str) -> list[EvaluationRun]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_json FROM evaluation_runs ORDER BY created_at"
            ).fetchall()
        return [
            run for row in rows
            if (run := EvaluationRun.model_validate_json(row[0])).trial_group_id == trial_group_id
        ]

    def acquire_lease(
        self, run_id: str, owner: str, *, lease_seconds: int = 60
    ) -> EvaluationLease | None:
        self.migrate()
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM evaluation_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None or row["status"] not in CLAIMABLE_RUN_STATUSES:
                connection.rollback()
                return None
            active = connection.execute(
                "SELECT expires_at FROM evaluation_run_leases WHERE run_id=?", (run_id,)
            ).fetchone()
            if active and active["expires_at"] > _now():
                connection.rollback()
                return None
            connection.execute("DELETE FROM evaluation_run_leases WHERE run_id=?", (run_id,))
            connection.execute(
                """INSERT INTO evaluation_run_leases(
                   run_id,lease_owner,lease_token_hash,acquired_at,heartbeat_at,expires_at
                   ) VALUES(?,?,?,?,?,?)""",
                (run_id, owner, _sha(token), _iso(now), _iso(now), _iso(expires)),
            )
            connection.commit()
        return EvaluationLease(run_id, owner, token, expires)

    def renew_lease(self, lease: EvaluationLease, *, lease_seconds: int = 60) -> EvaluationLease:
        expires = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE evaluation_run_leases SET heartbeat_at=?,expires_at=?
                   WHERE run_id=? AND lease_owner=? AND lease_token_hash=?""",
                (_now(), _iso(expires), lease.run_id, lease.owner, _sha(lease.token)),
            )
            if cursor.rowcount != 1:
                raise EvaluationStoreError("evaluation_lease_lost", retryable=True)
        return EvaluationLease(lease.run_id, lease.owner, lease.token, expires)

    def release_lease(self, lease: EvaluationLease) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM evaluation_run_leases WHERE run_id=? AND lease_owner=? AND lease_token_hash=?",
                (lease.run_id, lease.owner, _sha(lease.token)),
            )

    def _immutable_json(
        self, table: str, key_column: str, key: str, json_column: str, model: BaseModel,
        columns: tuple[str, ...], values: tuple, error_code: str,
    ) -> None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {json_column} FROM {table} WHERE {key_column}=?", (key,)
            ).fetchone()
            encoded = _model_json(model)
            if row:
                if row[0] != encoded:
                    raise EvaluationStoreError(error_code, key)
                return
            names = (key_column,) + columns + (json_column,)
            placeholders = ",".join("?" for _ in names)
            connection.execute(
                f"INSERT INTO {table}({','.join(names)}) VALUES({placeholders})",
                (key,) + values + (encoded,),
            )

    def _upsert_draft(
        self, table: str, key_column: str, key: str, json_column: str, model: BaseModel,
        columns: tuple[str, ...], values: tuple, *, terminal: bool,
    ) -> None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT status,{json_column} FROM {table} WHERE {key_column}=?", (key,)
            ).fetchone()
            if row and row["status"] != "draft" and row[json_column] != _model_json(model):
                raise EvaluationStoreError("evaluation_dataset_immutable")
            if row is None:
                names = (key_column,) + columns + (json_column,)
                placeholders = ",".join("?" for _ in names)
                connection.execute(
                    f"INSERT INTO {table}({','.join(names)}) VALUES({placeholders})",
                    (key,) + values + (_model_json(model),),
                )
            elif row["status"] == "draft":
                assignments = ",".join(f"{column}=?" for column in columns + (json_column,))
                connection.execute(
                    f"UPDATE {table} SET {assignments} WHERE {key_column}=? AND status='draft'",
                    values + (_model_json(model), key),
                )

    def _get_model(self, table, key_column, key, json_column, model_type, error_code):
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {json_column} FROM {table} WHERE {key_column}=?", (key,)
            ).fetchone()
        if row is None:
            raise EvaluationStoreError(error_code, key)
        return model_type.model_validate_json(row[0])

    def _list_models(self, table, key_column, key, json_column, model_type):
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {json_column} FROM {table} WHERE {key_column}=? ORDER BY rowid", (key,)
            ).fetchall()
        return [model_type.model_validate_json(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


def _model_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
