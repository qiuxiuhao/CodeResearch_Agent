from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from backend.app.agents.research.schemas import (
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    ResearchPlan,
    ResearchRunCreateRequest,
    ResearchRunStatus,
)


MIGRATIONS_DIR = Path(__file__).with_name("research_migrations")
RESEARCH_RUN_SCHEMA_VERSION = 1


class ResearchRunStoreError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class RunLease:
    run_id: str
    owner: str
    token: str
    expires_at: datetime


class ResearchRunStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > RESEARCH_RUN_SCHEMA_VERSION:
                raise ResearchRunStoreError(
                    "research_run_schema_too_new",
                    f"Research run database version {current} is newer than supported version {RESEARCH_RUN_SCHEMA_VERSION}.",
                )
            for version in range(current + 1, RESEARCH_RUN_SCHEMA_VERSION + 1):
                migration = MIGRATIONS_DIR / f"{version:03d}_research_runs.sql"
                if not migration.is_file():
                    raise ResearchRunStoreError("research_run_migration_missing", migration.name)
                connection.executescript(migration.read_text(encoding="utf-8"))

    def create_run(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        request: ResearchRunCreateRequest,
        caller_scope: str,
        idempotency_key: str | None = None,
        graph_version: str = "1.0",
        state_schema_version: str = "1.0",
    ) -> tuple[dict, bool]:
        self.migrate()
        request_json = _canonical_json(request.model_dump(mode="json"))
        request_hash_value = request_hash(repo_id, index_version_id, request)
        caller_scope_hash = _sha256(caller_scope.strip() or "anonymous")
        key_hash = _sha256(idempotency_key) if idempotency_key else None
        if key_hash:
            existing = self._find_idempotent(caller_scope_hash, key_hash)
            if existing:
                if existing["request_hash"] != request_hash_value:
                    raise ResearchRunStoreError(
                        "idempotency_key_conflict",
                        "The Idempotency-Key was already used with a different request.",
                    )
                return existing, True
        now = _now()
        run_id = f"run_{uuid4().hex}"
        values = (
            run_id, run_id, repo_id, index_version_id, request.parent_run_id,
            request.continued_from_run_id, _canonical_json(request.seed_evidence_ids),
            request_json, request_hash_value, key_hash, caller_scope_hash, graph_version,
            state_schema_version, now, now,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO research_runs(
                           run_id, thread_id, repo_id, index_version_id, parent_run_id,
                           continued_from_run_id, seed_evidence_ids_json, request_json,
                           request_hash, idempotency_key_hash, caller_scope_hash, status,
                           graph_version, state_schema_version, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)""",
                    values,
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            if key_hash:
                existing = self._find_idempotent(caller_scope_hash, key_hash)
                if existing and existing["request_hash"] == request_hash_value:
                    return existing, True
                raise ResearchRunStoreError("idempotency_key_conflict", str(exc)) from exc
            raise
        return self.get_run(run_id), False

    def get_run(self, run_id: str) -> dict:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT r.*, l.lease_owner, l.lease_expires_at
                   FROM research_runs r LEFT JOIN research_run_leases l ON l.run_id=r.run_id
                   WHERE r.run_id=?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ResearchRunStoreError("agent_run_not_found", f"Research run {run_id} was not found.")
        return _row_dict(row)

    def get_run_for_caller(self, run_id: str, caller_scope: str) -> dict:
        run = self.get_run(run_id)
        if run["caller_scope_hash"] != _sha256(caller_scope.strip() or "anonymous"):
            raise ResearchRunStoreError(
                "agent_run_forbidden", "The caller is not authorized to access this research run."
            )
        return run

    def update_status(
        self,
        run_id: str,
        target: ResearchRunStatus,
        *,
        allowed_from: Iterable[str],
        route: str | None = None,
        stop_reason: str | None = None,
        retryable: bool | None = None,
        result: dict | None = None,
        budget: dict | None = None,
        errors: list[dict] | None = None,
        checkpoint_id: str | None = None,
    ) -> dict:
        allowed = tuple(dict.fromkeys(allowed_from))
        if not allowed:
            raise ValueError("allowed_from must not be empty")
        current = self.get_run(run_id)
        if current["status"] in TERMINAL_STATUSES:
            if current["status"] == target:
                return current
            raise ResearchRunStoreError(
                "invalid_run_transition", f"Terminal run {run_id} cannot transition to {target}."
            )
        now = _now()
        terminal = target in TERMINAL_STATUSES
        placeholders = ",".join("?" for _ in allowed)
        updates = ["status=?", "updated_at=?"]
        params: list[object] = [target, now]
        if route is not None:
            updates.append("route=?")
            params.append(route)
        if stop_reason is not None:
            updates.append("stop_reason=?")
            params.append(stop_reason)
        if retryable is not None:
            updates.append("retryable=?")
            params.append(int(retryable))
        if result is not None:
            updates.append("result_json=?")
            params.append(_canonical_json(result))
        if budget is not None:
            updates.append("budget_json=?")
            params.append(_canonical_json(budget))
        if errors is not None:
            updates.append("errors_json=?")
            params.append(_canonical_json(errors))
        if checkpoint_id is not None:
            updates.append("checkpoint_id=?")
            params.append(checkpoint_id)
        if terminal:
            updates.append("finished_at=?")
            params.append(now)
        elif target not in {"queued", "paused", "interrupted", "cancelling"}:
            updates.append("started_at=COALESCE(started_at, ?)")
            params.append(now)
        params.extend([run_id, *allowed])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE research_runs SET {', '.join(updates)} WHERE run_id=? AND status IN ({placeholders})",
                params,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                latest = self.get_run(run_id)
                if latest["status"] == target:
                    return latest
                raise ResearchRunStoreError(
                    "invalid_run_transition",
                    f"Run {run_id} in state {latest['status']} cannot transition to {target}.",
                )
            connection.commit()
        return self.get_run(run_id)

    def request_cancel(self, run_id: str) -> dict:
        current = self.get_run(run_id)
        if current["status"] in TERMINAL_STATUSES:
            return current
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE research_runs SET cancel_requested=1, status='cancelling', updated_at=?
                   WHERE run_id=? AND status NOT IN ('completed','partial','failed','cancelled')""",
                (now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def is_cancel_requested(self, run_id: str) -> bool:
        return bool(self.get_run(run_id)["cancel_requested"])

    def save_plan(
        self,
        run_id: str,
        plan: ResearchPlan,
        *,
        planner_request_hash: str,
        replaced_reason: str | None = None,
    ) -> None:
        self.migrate()
        now = _now()
        payload = _canonical_json(plan.model_dump(mode="json"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT canonical_plan_json FROM research_plan_versions WHERE plan_id=? AND run_id=?",
                (plan.plan_id, run_id),
            ).fetchone()
            if existing is not None:
                if existing["canonical_plan_json"] != payload:
                    connection.rollback()
                    raise ResearchRunStoreError(
                        "plan_id_conflict", "The same plan_id cannot identify different plan content."
                    )
                connection.execute(
                    "UPDATE research_runs SET current_plan_id=?, current_plan_version=?, updated_at=? WHERE run_id=?",
                    (plan.plan_id, plan.plan_version, now, run_id),
                )
                connection.commit()
                return
            connection.execute(
                "UPDATE research_plan_versions SET status='superseded', replaced_reason=? WHERE run_id=? AND status='active'",
                (replaced_reason, run_id),
            )
            connection.execute(
                """INSERT INTO research_plan_versions(
                       plan_id, run_id, plan_version, canonical_plan_json,
                       planner_request_hash, status, replaced_reason, created_at
                   ) VALUES (?, ?, ?, ?, ?, 'active', NULL, ?)
                   ON CONFLICT(plan_id) DO NOTHING""",
                (plan.plan_id, run_id, plan.plan_version, payload, planner_request_hash, now),
            )
            connection.execute(
                "UPDATE research_runs SET current_plan_id=?, current_plan_version=?, updated_at=? WHERE run_id=?",
                (plan.plan_id, plan.plan_version, now, run_id),
            )
            connection.commit()

    def list_plan_versions(self, run_id: str) -> list[dict]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_plan_versions WHERE run_id=? ORDER BY created_at, plan_version",
                (run_id,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def acquire_lease(self, run_id: str, owner: str, *, ttl_seconds: float = 30.0) -> RunLease | None:
        self.migrate()
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=max(1.0, ttl_seconds))
        token = uuid4().hex
        token_hash = _sha256(token)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM research_run_leases WHERE run_id=?", (run_id,)
            ).fetchone()
            if current is not None:
                current_expiry = _parse_time(current["lease_expires_at"])
                if current_expiry > now and current["lease_owner"] != owner:
                    connection.rollback()
                    return None
            connection.execute(
                """INSERT INTO research_run_leases(
                       run_id, lease_owner, lease_token_hash, lease_acquired_at,
                       lease_expires_at, last_heartbeat_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       lease_owner=excluded.lease_owner,
                       lease_token_hash=excluded.lease_token_hash,
                       lease_acquired_at=excluded.lease_acquired_at,
                       lease_expires_at=excluded.lease_expires_at,
                       last_heartbeat_at=excluded.last_heartbeat_at""",
                (run_id, owner, token_hash, _iso(now), _iso(expires), _iso(now)),
            )
            connection.commit()
        return RunLease(run_id, owner, token, expires)

    def renew_lease(self, lease: RunLease, *, ttl_seconds: float = 30.0) -> RunLease | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=max(1.0, ttl_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE research_run_leases SET lease_expires_at=?, last_heartbeat_at=?
                   WHERE run_id=? AND lease_owner=? AND lease_token_hash=?""",
                (_iso(expires), _iso(now), lease.run_id, lease.owner, _sha256(lease.token)),
            )
            connection.commit()
        return RunLease(lease.run_id, lease.owner, lease.token, expires) if cursor.rowcount == 1 else None

    def release_lease(self, lease: RunLease) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM research_run_leases WHERE run_id=? AND lease_owner=? AND lease_token_hash=?",
                (lease.run_id, lease.owner, _sha256(lease.token)),
            )
            connection.commit()
        return cursor.rowcount == 1

    def list_claimable(self, *, limit: int = 20) -> list[str]:
        self.migrate()
        now = _now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT r.run_id FROM research_runs r
                   LEFT JOIN research_run_leases l ON l.run_id=r.run_id
                   WHERE r.status NOT IN ('completed','partial','failed','cancelled','paused')
                     AND (r.status='queued' OR l.run_id IS NULL OR l.lease_expires_at<=?)
                   ORDER BY r.created_at LIMIT ?""",
                (now, max(1, min(limit, 100))),
            ).fetchall()
        return [str(row["run_id"]) for row in rows]

    def mark_resumed(self, run_id: str) -> dict:
        current = self.get_run(run_id)
        if current["status"] not in RESUMABLE_STATUSES:
            raise ResearchRunStoreError("resume_not_allowed", f"Run {run_id} cannot be resumed.")
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE research_runs SET resume_count=resume_count+1, status='interrupted',
                       last_resumed_at=?, updated_at=? WHERE run_id=? AND status IN ('paused','interrupted')""",
                (now, now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def terminal_runs_before(self, cutoff: datetime, *, limit: int = 100) -> list[dict]:
        self.migrate()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM research_runs
                   WHERE status IN ('completed','partial','failed','cancelled')
                     AND finished_at IS NOT NULL AND finished_at < ?
                   ORDER BY finished_at LIMIT ?""",
                (_iso(cutoff), max(1, min(limit, 1000))),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def delete_terminal_run(self, run_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """DELETE FROM research_runs WHERE run_id=?
                   AND status IN ('completed','partial','failed','cancelled')""",
                (run_id,),
            )
            connection.commit()
        return cursor.rowcount == 1

    def _find_idempotent(self, caller_scope_hash: str, key_hash: str) -> dict | None:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_runs WHERE caller_scope_hash=? AND idempotency_key_hash=?",
                (caller_scope_hash, key_hash),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


def request_hash(repo_id: str, index_version_id: str, request: ResearchRunCreateRequest) -> str:
    return _sha256(_canonical_json({
        "repo_id": repo_id,
        "index_version_id": index_version_id,
        "request": request.model_dump(mode="json"),
    }))


def _row_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    for key in ("seed_evidence_ids_json", "request_json", "result_json", "budget_json", "errors_json"):
        if key in result:
            target = key.removesuffix("_json")
            value = result.pop(key)
            result[target] = json.loads(value) if value else ([] if key.endswith("ids_json") else {})
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    result["retryable"] = bool(result.get("retryable"))
    return result


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return _iso(datetime.now(UTC))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
