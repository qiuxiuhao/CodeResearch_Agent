from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

from pydantic import BaseModel

from backend.app.alignment.schemas import (
    AlignmentCandidate,
    AlignmentCandidateScore,
    AlignmentDecision,
    AlignmentDeployment,
    AlignmentFeatureVector,
    AlignmentModelProfile,
    AlignmentReview,
    AlignmentRun,
    AlignmentVerification,
    PaperModuleProfile,
)
from backend.app.alignment.stable_ids import deployment_id, run_id as stable_run_id


MIGRATIONS_DIR = Path(__file__).with_name("alignment_migrations")
ALIGNMENT_SCHEMA_VERSION = 1
TERMINAL_STATUSES = {"active", "failed", "superseded", "cancelled"}
BUILD_STATUSES = {"queued", "profiling", "recalling", "featurizing", "scoring", "verifying", "ready"}


class AlignmentStoreError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class AlignmentLease:
    run_id: str
    owner: str
    token: str
    expires_at: datetime


class AlignmentStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > ALIGNMENT_SCHEMA_VERSION:
                raise AlignmentStoreError("alignment_schema_too_new", str(current))
            for version in range(current + 1, ALIGNMENT_SCHEMA_VERSION + 1):
                migration = MIGRATIONS_DIR / f"{version:03d}_alignment.sql"
                if not migration.is_file():
                    raise AlignmentStoreError("alignment_migration_missing", migration.name)
                connection.executescript(migration.read_text(encoding="utf-8"))

    def save_model_profile(self, profile: AlignmentModelProfile) -> None:
        self.migrate()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO alignment_model_profiles(model_profile_id,config_hash,profile_json,created_at)
                   VALUES(?,?,?,?) ON CONFLICT(model_profile_id) DO NOTHING""",
                (profile.model_profile_id, profile.config_hash, _json_model(profile), _now()),
            )

    def create_run(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        paper_id: str,
        input_hash: str,
        model_profile_id: str,
        request: dict,
        caller_scope: str,
        idempotency_key: str | None = None,
        retry_of_run_id: str | None = None,
    ) -> tuple[dict, bool]:
        self.migrate()
        request_json = _json(request)
        request_hash = _sha256(request_json)
        caller_hash = _sha256(caller_scope.strip() or "anonymous")
        key_hash = _sha256(idempotency_key) if idempotency_key else None
        if key_hash:
            existing = self._idempotent(caller_hash, key_hash)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise AlignmentStoreError("idempotency_key_conflict", "Idempotency-Key request mismatch.")
                return existing, True
        reusable = self.find_successful(repo_id, index_version_id, paper_id, input_hash, model_profile_id)
        if reusable:
            return reusable, True
        attempt = 1
        if retry_of_run_id:
            parent = self.get_run(retry_of_run_id)
            if parent["status"] not in {"failed", "cancelled"}:
                raise AlignmentStoreError("alignment_retry_not_allowed", "Only failed/cancelled runs may be retried.")
            identity = (repo_id, index_version_id, paper_id, input_hash, model_profile_id)
            if identity != tuple(parent[key] for key in ("repo_id", "index_version_id", "paper_id", "input_hash", "model_profile_id")):
                raise AlignmentStoreError("alignment_retry_identity_mismatch", "Retry identity must remain fixed.")
            attempt = int(parent["attempt_number"]) + 1
        identifier = stable_run_id(
            repo_id=repo_id,
            index_version_id=index_version_id,
            paper_id=paper_id,
            input_hash=input_hash,
            attempt=attempt,
        )
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO alignment_runs(
                         run_id,repo_id,index_version_id,paper_id,input_hash,model_profile_id,
                         attempt_number,retry_of_run_id,request_json,request_hash,idempotency_key_hash,
                         caller_scope_hash,status,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'queued',?,?)""",
                    (
                        identifier, repo_id, index_version_id, paper_id, input_hash,
                        model_profile_id, attempt, retry_of_run_id, request_json, request_hash,
                        key_hash, caller_hash, now, now,
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            if key_hash:
                existing = self._idempotent(caller_hash, key_hash)
                if existing and existing["request_hash"] == request_hash:
                    return existing, True
            raise AlignmentStoreError("alignment_run_conflict", str(exc), retryable=True) from exc
        return self.get_run(identifier), False

    def get_run(self, run_id: str) -> dict:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT r.*,l.lease_owner,l.expires_at AS lease_expires_at
                   FROM alignment_runs r LEFT JOIN alignment_run_leases l ON l.run_id=r.run_id
                   WHERE r.run_id=?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise AlignmentStoreError("alignment_run_not_found", run_id)
        return dict(row)

    def get_run_for_caller(self, run_id: str, caller_scope: str) -> dict:
        run = self.get_run(run_id)
        if run["caller_scope_hash"] != _sha256(caller_scope.strip() or "anonymous"):
            raise AlignmentStoreError("alignment_run_forbidden", run_id)
        return run

    def find_successful(
        self, repo_id: str, index_version_id: str, paper_id: str, input_hash: str, model_profile_id: str
    ) -> dict | None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM alignment_runs WHERE repo_id=? AND index_version_id=? AND paper_id=?
                   AND input_hash=? AND model_profile_id=? AND status IN ('active','ready','superseded')
                   ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'ready' THEN 1 ELSE 2 END LIMIT 1""",
                (repo_id, index_version_id, paper_id, input_hash, model_profile_id),
            ).fetchone()
        return dict(row) if row else None

    def list_claimable_runs(self, limit: int = 20) -> list[dict]:
        self.migrate()
        now = _now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT r.* FROM alignment_runs r
                   LEFT JOIN alignment_run_leases l ON l.run_id=r.run_id
                   WHERE r.status IN ('queued','profiling','recalling','featurizing','scoring','verifying','ready')
                     AND (l.run_id IS NULL OR l.expires_at<=?)
                   ORDER BY r.created_at LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def acquire_lease(self, run_id: str, owner: str, *, lease_seconds: int = 60) -> AlignmentLease | None:
        self.migrate()
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT status FROM alignment_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["status"] not in BUILD_STATUSES:
                connection.rollback()
                return None
            existing = connection.execute("SELECT expires_at FROM alignment_run_leases WHERE run_id=?", (run_id,)).fetchone()
            if existing and existing["expires_at"] > _now():
                connection.rollback()
                return None
            connection.execute("DELETE FROM alignment_run_leases WHERE run_id=?", (run_id,))
            connection.execute(
                """INSERT INTO alignment_run_leases(run_id,lease_owner,lease_token_hash,acquired_at,heartbeat_at,expires_at)
                   VALUES(?,?,?,?,?,?)""",
                (run_id, owner, _sha256(token), now.isoformat(), now.isoformat(), expires.isoformat()),
            )
            connection.commit()
        return AlignmentLease(run_id, owner, token, expires)

    def renew_lease(self, lease: AlignmentLease, *, lease_seconds: int = 60) -> AlignmentLease:
        expires = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE alignment_run_leases SET heartbeat_at=?,expires_at=?
                   WHERE run_id=? AND lease_owner=? AND lease_token_hash=?""",
                (_now(), expires.isoformat(), lease.run_id, lease.owner, _sha256(lease.token)),
            )
            if cursor.rowcount != 1:
                raise AlignmentStoreError("alignment_lease_lost", lease.run_id, retryable=True)
        return AlignmentLease(lease.run_id, lease.owner, lease.token, expires)

    def assert_lease(self, lease: AlignmentLease) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT expires_at FROM alignment_run_leases
                   WHERE run_id=? AND lease_owner=? AND lease_token_hash=?""",
                (lease.run_id, lease.owner, _sha256(lease.token)),
            ).fetchone()
        if row is None or row["expires_at"] <= _now():
            raise AlignmentStoreError("alignment_lease_lost", lease.run_id, retryable=True)

    def release_lease(self, lease: AlignmentLease) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM alignment_run_leases WHERE run_id=? AND lease_owner=? AND lease_token_hash=?",
                (lease.run_id, lease.owner, _sha256(lease.token)),
            )

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        allowed_from: Iterable[str],
        error_code: str | None = None,
        error: dict | None = None,
    ) -> dict:
        allowed = tuple(allowed_from)
        if not allowed:
            raise ValueError("allowed_from cannot be empty")
        placeholders = ",".join("?" for _ in allowed)
        finished = _now() if status in TERMINAL_STATUSES else None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"""UPDATE alignment_runs SET status=?,current_stage=?,error_code=?,error_json=?,
                    updated_at=?,finished_at=COALESCE(?,finished_at)
                    WHERE run_id=? AND status IN ({placeholders})""",
                (status, status, error_code, _json(error) if error else None, _now(), finished, run_id, *allowed),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                latest = self.get_run(run_id)
                if latest["status"] == status:
                    return latest
                raise AlignmentStoreError("invalid_alignment_transition", f"{latest['status']} -> {status}")
            connection.commit()
        return self.get_run(run_id)

    def request_cancel(self, run_id: str) -> dict:
        run = self.get_run(run_id)
        if run["status"] in {"ready", "active", "superseded"}:
            raise AlignmentStoreError("alignment_cancel_not_allowed", run_id)
        if run["status"] in {"failed", "cancelled"}:
            return run
        with self._connect() as connection:
            connection.execute(
                "UPDATE alignment_runs SET cancel_requested=1,updated_at=? WHERE run_id=?",
                (_now(), run_id),
            )
        return self.get_run(run_id)

    def is_cancel_requested(self, run_id: str) -> bool:
        return bool(self.get_run(run_id)["cancel_requested"])

    def save_profiles(self, run_id: str, profiles: Sequence[PaperModuleProfile]) -> None:
        self._replace_models(
            run_id,
            "paper_module_profiles",
            "profile_id",
            profiles,
            lambda item: (item.profile_id, item.profile_type, item.granularity, item.source_group_key, item.content_hash, _json_model(item)),
            "profile_id,profile_type,granularity,source_group_key,content_hash,profile_json",
            "profile_count",
            "profiling",
        )

    def save_candidates(self, run_id: str, candidates: Sequence[AlignmentCandidate]) -> None:
        self._replace_models(
            run_id,
            "alignment_candidates",
            "candidate_id",
            candidates,
            lambda item: (item.candidate_id, item.profile_id, item.code_entity_id, item.candidate_status, _json_model(item)),
            "candidate_id,profile_id,code_entity_id,candidate_status,candidate_json",
            "candidate_count",
            "recalling",
        )

    def save_features(self, run_id: str, vectors: Sequence[AlignmentFeatureVector]) -> None:
        self._replace_models(
            run_id,
            "alignment_feature_values",
            "vector_id",
            vectors,
            lambda item: (item.vector_id, item.profile_id, item.candidate_id, _json_model(item)),
            "vector_id,profile_id,candidate_id,feature_json",
            None,
            "featurizing",
        )

    def save_scores(self, run_id: str, scores: Sequence[AlignmentCandidateScore]) -> None:
        self._replace_models(
            run_id,
            "alignment_candidate_scores",
            "score_id",
            scores,
            lambda item: (item.score_id, item.profile_id, item.candidate_id, _json_model(item)),
            "score_id,profile_id,candidate_id,score_json",
            None,
            "scoring",
        )

    def save_decisions(self, run_id: str, decisions: Sequence[AlignmentDecision]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT stage_manifest_json FROM alignment_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                connection.rollback()
                raise AlignmentStoreError("alignment_run_not_found", run_id)
            connection.execute("DELETE FROM alignment_selections WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM alignment_decisions WHERE run_id=?", (run_id,))
            for item in decisions:
                connection.execute(
                    """INSERT INTO alignment_decisions(
                         run_id,decision_id,profile_id,decision_version,status,decision_json
                       ) VALUES(?,?,?,?,?,?)""",
                    (run_id, item.decision_id, item.profile_id, item.decision_version, item.status, _json_model(item)),
                )
                for selection in item.selections:
                    connection.execute(
                        """INSERT INTO alignment_selections(
                             run_id,decision_id,selection_id,candidate_id,relation_type,selection_json
                           ) VALUES(?,?,?,?,?,?)""",
                        (run_id, item.decision_id, selection.selection_id, selection.candidate_id, selection.relation_type, _json_model(selection)),
                    )
            counts = {
                "decision_count": len(decisions),
                "accepted_count": sum(item.status == "accepted" for item in decisions),
                "abstained_count": sum(item.status == "abstained" for item in decisions),
                "needs_review_count": sum(item.status == "needs_review" for item in decisions),
            }
            manifest = _stage_manifest(run["stage_manifest_json"], "scoring", counts)
            connection.execute(
                """UPDATE alignment_runs SET decision_count=?,accepted_count=?,abstained_count=?,
                   needs_review_count=?,current_stage='scoring',stage_manifest_json=?,updated_at=? WHERE run_id=?""",
                (*counts.values(), _json(manifest), _now(), run_id),
            )
            connection.commit()

    def save_verifications(self, run_id: str, items: Sequence[AlignmentVerification]) -> None:
        self._replace_models(
            run_id,
            "alignment_verifications",
            "verification_id",
            items,
            lambda item: (item.verification_id, item.profile_id, _json_model(item)),
            "verification_id,profile_id,verification_json",
            None,
            "verifying",
        )

    def load_profiles(self, run_id: str) -> list[PaperModuleProfile]:
        return self._load_models(
            "paper_module_profiles", "profile_json", run_id, PaperModuleProfile
        )

    def load_candidates(self, run_id: str) -> list[AlignmentCandidate]:
        return self._load_models(
            "alignment_candidates", "candidate_json", run_id, AlignmentCandidate
        )

    def load_features(self, run_id: str) -> list[AlignmentFeatureVector]:
        return self._load_models(
            "alignment_feature_values", "feature_json", run_id, AlignmentFeatureVector
        )

    def load_scores(self, run_id: str) -> list[AlignmentCandidateScore]:
        return self._load_models(
            "alignment_candidate_scores", "score_json", run_id, AlignmentCandidateScore
        )

    def load_decisions(self, run_id: str) -> list[AlignmentDecision]:
        return self._load_models(
            "alignment_decisions", "decision_json", run_id, AlignmentDecision
        )

    def mark_ready_and_activate(self, run_id: str) -> dict:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM alignment_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["status"] not in {"scoring", "verifying", "ready"}:
                connection.rollback()
                raise AlignmentStoreError("alignment_not_ready", run_id)
            profile_count = connection.execute("SELECT COUNT(*) FROM paper_module_profiles WHERE run_id=?", (run_id,)).fetchone()[0]
            decision_count = connection.execute("SELECT COUNT(*) FROM alignment_decisions WHERE run_id=?", (run_id,)).fetchone()[0]
            if profile_count != decision_count:
                connection.rollback()
                raise AlignmentStoreError("alignment_integrity_error", "Every profile requires a decision.")
            connection.execute(
                """UPDATE alignment_runs SET status='superseded',updated_at=?
                   WHERE repo_id=? AND index_version_id=? AND paper_id=? AND model_profile_id=? AND status='active'""",
                (_now(), run["repo_id"], run["index_version_id"], run["paper_id"], run["model_profile_id"]),
            )
            connection.execute(
                """UPDATE alignment_runs SET status='active',current_stage='active',activated_at=?,updated_at=?
                   WHERE run_id=?""",
                (_now(), _now(), run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def set_deployment(
        self,
        *,
        deployment_name: str,
        repo_id: str,
        index_version_id: str,
        paper_id: str,
        model_profile_id: str,
        active_run_id: str,
    ) -> AlignmentDeployment:
        run = self.get_run(active_run_id)
        expected = (repo_id, index_version_id, paper_id, model_profile_id, "active")
        actual = tuple(run[key] for key in ("repo_id", "index_version_id", "paper_id", "model_profile_id", "status"))
        if actual != expected:
            raise AlignmentStoreError("alignment_deployment_run_mismatch", active_run_id)
        identifier = deployment_id(
            name=deployment_name,
            repo_id=repo_id,
            index_version_id=index_version_id,
            paper_id=paper_id,
        )
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO alignment_deployments(
                     deployment_id,deployment_name,repo_id,index_version_id,paper_id,model_profile_id,
                     active_run_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(deployment_name,repo_id,index_version_id,paper_id) DO UPDATE SET
                     model_profile_id=excluded.model_profile_id,active_run_id=excluded.active_run_id,
                     updated_at=excluded.updated_at""",
                (identifier, deployment_name, repo_id, index_version_id, paper_id, model_profile_id, active_run_id, now, now),
            )
        return self.get_deployment(repo_id, index_version_id, paper_id, deployment_name)

    def get_deployment(
        self, repo_id: str, index_version_id: str, paper_id: str, deployment_name: str = "default"
    ) -> AlignmentDeployment:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM alignment_deployments WHERE deployment_name=? AND repo_id=?
                   AND index_version_id=? AND paper_id=?""",
                (deployment_name, repo_id, index_version_id, paper_id),
            ).fetchone()
        if row is None:
            raise AlignmentStoreError("alignment_profile_required", "No alignment deployment is configured.")
        return AlignmentDeployment.model_validate(dict(row))

    def list_deployments(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        deployment_name: str = "default",
    ) -> list[AlignmentDeployment]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM alignment_deployments WHERE deployment_name=? AND repo_id=?
                   AND index_version_id=? ORDER BY paper_id""",
                (deployment_name, repo_id, index_version_id),
            ).fetchall()
        return [AlignmentDeployment.model_validate(dict(row)) for row in rows]

    def candidate_entities(self, run_id: str) -> dict[str, str]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT candidate_id,code_entity_id FROM alignment_candidates WHERE run_id=?",
                (run_id,),
            ).fetchall()
        return {str(row["candidate_id"]): str(row["code_entity_id"]) for row in rows}

    def list_decisions(self, run_id: str, status: str | None = None) -> list[AlignmentDecision]:
        clauses = ["run_id=?"]
        params: list[object] = [run_id]
        if status:
            clauses.append("status=?")
            params.append(status)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT decision_json FROM alignment_decisions WHERE {' AND '.join(clauses)} ORDER BY profile_id",
                params,
            ).fetchall()
        return [AlignmentDecision.model_validate_json(row["decision_json"]) for row in rows]

    def find_active_run(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        paper_id: str,
        model_profile_id: str,
    ) -> dict:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM alignment_runs WHERE repo_id=? AND index_version_id=? AND paper_id=?
                   AND model_profile_id=? AND status='active'""",
                (repo_id, index_version_id, paper_id, model_profile_id),
            ).fetchone()
        if row is None:
            raise AlignmentStoreError("alignment_version_not_ready", model_profile_id)
        return dict(row)

    def delete_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        if run["status"] == "active":
            raise AlignmentStoreError("alignment_retention_not_allowed", "Active run cannot be deleted.")
        with self._connect() as connection:
            referenced = connection.execute(
                "SELECT 1 FROM alignment_deployments WHERE active_run_id=?", (run_id,)
            ).fetchone()
            if referenced:
                raise AlignmentStoreError("alignment_retention_not_allowed", "Deployed run cannot be deleted.")
            connection.execute("DELETE FROM alignment_runs WHERE run_id=?", (run_id,))

    def get_decision_row(self, decision_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM alignment_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if row is None:
            raise AlignmentStoreError("alignment_decision_not_found", decision_id)
        return dict(row)

    def get_decision_detail(self, decision_id: str) -> dict:
        decision_row = self.get_decision_row(decision_id)
        run_id = decision_row["run_id"]
        profile_id = decision_row["profile_id"]
        with self._connect() as connection:
            profile = connection.execute(
                "SELECT profile_json FROM paper_module_profiles WHERE run_id=? AND profile_id=?",
                (run_id, profile_id),
            ).fetchone()
            candidate_rows = connection.execute(
                "SELECT candidate_json FROM alignment_candidates WHERE run_id=? AND profile_id=? ORDER BY candidate_id",
                (run_id, profile_id),
            ).fetchall()
            feature_rows = connection.execute(
                "SELECT feature_json FROM alignment_feature_values WHERE run_id=? AND profile_id=? ORDER BY candidate_id",
                (run_id, profile_id),
            ).fetchall()
            score_rows = connection.execute(
                "SELECT score_json FROM alignment_candidate_scores WHERE run_id=? AND profile_id=? ORDER BY candidate_id",
                (run_id, profile_id),
            ).fetchall()
            verification_rows = connection.execute(
                "SELECT verification_json FROM alignment_verifications WHERE run_id=? AND profile_id=? ORDER BY verification_id",
                (run_id, profile_id),
            ).fetchall()
        return {
            "run_id": run_id,
            "profile": json.loads(profile["profile_json"]) if profile else None,
            "decision": json.loads(decision_row["decision_json"]),
            "candidates": [json.loads(row["candidate_json"]) for row in candidate_rows],
            "features": [json.loads(row["feature_json"]) for row in feature_rows],
            "scores": [json.loads(row["score_json"]) for row in score_rows],
            "verifications": [
                json.loads(row["verification_json"]) for row in verification_rows
            ],
        }

    def add_review(self, review: AlignmentReview) -> None:
        row = self.get_decision_row(review.decision_id)
        if int(row["effective_revision"]) != review.based_on_effective_revision:
            raise AlignmentStoreError("review_conflict", "Effective revision is stale.")
        candidate_ids = {item.candidate_id for item in review.selections}
        if candidate_ids:
            with self._connect() as connection:
                placeholders = ",".join("?" for _ in candidate_ids)
                candidate_rows = connection.execute(
                    f"SELECT candidate_id,candidate_json FROM alignment_candidates WHERE run_id=? AND candidate_id IN ({placeholders})",
                    (row["run_id"], *candidate_ids),
                ).fetchall()
                profile_row = connection.execute(
                    "SELECT profile_json FROM paper_module_profiles WHERE run_id=? AND profile_id=?",
                    (row["run_id"], row["profile_id"]),
                ).fetchone()
            if len(candidate_rows) != len(candidate_ids):
                raise AlignmentStoreError("candidate_not_in_run", "Review selected an unknown candidate.")
            candidates = {
                item["candidate_id"]: AlignmentCandidate.model_validate_json(item["candidate_json"])
                for item in candidate_rows
            }
            profile = PaperModuleProfile.model_validate_json(profile_row["profile_json"])
            for selection in review.selections:
                candidate = candidates[selection.candidate_id]
                if not set(selection.paper_evidence_ids) <= set(profile.evidence_ids):
                    raise AlignmentStoreError(
                        "alignment_review_evidence_invalid", "Review used unknown paper evidence."
                    )
                if not set(selection.code_evidence_ids) <= set(candidate.code_evidence_ids):
                    raise AlignmentStoreError(
                        "alignment_review_evidence_invalid", "Review used unknown code evidence."
                    )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT effective_revision,review_sequence FROM alignment_decisions WHERE decision_id=?",
                (review.decision_id,),
            ).fetchone()
            if int(latest["effective_revision"]) != review.based_on_effective_revision:
                connection.rollback()
                raise AlignmentStoreError("review_conflict", "Effective revision changed concurrently.")
            expected_sequence = int(latest["review_sequence"]) + 1
            if review.review_sequence != expected_sequence:
                connection.rollback()
                raise AlignmentStoreError("review_sequence_conflict", str(expected_sequence))
            connection.execute(
                """INSERT INTO alignment_reviews(
                     review_id,run_id,decision_id,review_sequence,based_on_effective_revision,review_json,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (review.review_id, row["run_id"], review.decision_id, review.review_sequence,
                 review.based_on_effective_revision, _json_model(review), review.created_at.isoformat()),
            )
            connection.execute(
                """UPDATE alignment_decisions SET effective_revision=effective_revision+1,
                   review_sequence=? WHERE decision_id=?""",
                (review.review_sequence, review.decision_id),
            )
            connection.commit()

    def list_reviews(self, decision_id: str) -> list[AlignmentReview]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT review_json FROM alignment_reviews WHERE decision_id=? ORDER BY review_sequence",
                (decision_id,),
            ).fetchall()
        return [AlignmentReview.model_validate_json(row["review_json"]) for row in rows]

    def _replace_models(
        self,
        run_id: str,
        table: str,
        _id_column: str,
        models: Sequence[BaseModel],
        values,
        columns: str,
        count_column: str | None,
        stage: str,
    ) -> None:
        placeholders = ",".join("?" for _ in columns.split(","))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT stage_manifest_json FROM alignment_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                connection.rollback()
                raise AlignmentStoreError("alignment_run_not_found", run_id)
            connection.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
            for item in models:
                connection.execute(
                    f"INSERT INTO {table}(run_id,{columns}) VALUES(?,{placeholders})",
                    (run_id, *values(item)),
                )
            updates = ["current_stage=?", "stage_manifest_json=?", "updated_at=?"]
            manifest = _stage_manifest(
                run["stage_manifest_json"], stage, {"count": len(models)}
            )
            params: list[object] = [stage, _json(manifest), _now()]
            if count_column:
                updates.append(f"{count_column}=?")
                params.append(len(models))
            params.append(run_id)
            connection.execute(f"UPDATE alignment_runs SET {','.join(updates)} WHERE run_id=?", params)
            connection.commit()

    def _idempotent(self, caller_hash: str, key_hash: str) -> dict | None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alignment_runs WHERE caller_scope_hash=? AND idempotency_key_hash=?",
                (caller_hash, key_hash),
            ).fetchone()
        return dict(row) if row else None

    def _load_models(self, table: str, column: str, run_id: str, model_type) -> list:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {column} FROM {table} WHERE run_id=? ORDER BY 1", (run_id,)
            ).fetchall()
        return [model_type.model_validate_json(row[column]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


def alignment_run_model(row: dict) -> AlignmentRun:
    return AlignmentRun(
        run_id=row["run_id"], repo_id=row["repo_id"], index_version_id=row["index_version_id"],
        paper_id=row["paper_id"], input_hash=row["input_hash"], model_profile_id=row["model_profile_id"],
        attempt_number=row["attempt_number"], retry_of_run_id=row["retry_of_run_id"], status=row["status"],
        cancel_requested=bool(row["cancel_requested"]), current_stage=row["current_stage"],
        profile_count=row["profile_count"], candidate_count=row["candidate_count"],
        decision_count=row["decision_count"], accepted_count=row["accepted_count"],
        abstained_count=row["abstained_count"], needs_review_count=row["needs_review_count"],
        error_code=row["error_code"], created_at=row["created_at"], updated_at=row["updated_at"],
        activated_at=row["activated_at"],
    )


def _json_model(model: BaseModel) -> str:
    return _json(model.model_dump(mode="json"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stage_manifest(raw: str | None, stage: str, values: dict) -> dict:
    try:
        manifest = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        manifest = {}
    manifest[stage] = values
    return manifest
