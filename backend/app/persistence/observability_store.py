from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from backend.app.observability.schemas import (
    SpanLink,
    SpanRecord,
    TelemetryCommand,
    TraceArtifactRef,
    TraceEvent,
    TraceFilter,
    TraceRecord,
)
from backend.app.observability.suppression import suppress_observability


class ObservabilityStoreError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ObservabilityStore:
    def __init__(self, db_path: str | Path, *, busy_timeout_ms: int = 2_000) -> None:
        self.db_path = Path(db_path)
        self.busy_timeout_ms = busy_timeout_ms

    def migrate(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        migration = Path(__file__).with_name("observability_migrations") / "001_observability.sql"
        with suppress_observability(), self._connect() as connection:
            connection.executescript(migration.read_text(encoding="utf-8"))

    def apply_commands(self, commands: Iterable[TelemetryCommand]) -> int:
        items = list(commands)
        if not items:
            return 0
        now = _now()
        applied = 0
        trace_ids: set[str] = set()
        with suppress_observability(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for command in items:
                    inserted = connection.execute(
                        """
                        INSERT OR IGNORE INTO telemetry_commands(
                            command_id,trace_id,span_id,command_type,lifecycle_sequence,
                            occurred_at,applied_at,result
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            command.command_id, command.trace_id, command.span_id,
                            command.command_type, command.lifecycle_sequence,
                            command.occurred_at.isoformat(), now, "applied",
                        ),
                    ).rowcount
                    if not inserted:
                        continue
                    self._apply_one(connection, command)
                    applied += 1
                    trace_ids.add(command.trace_id)
                for trace_id in trace_ids:
                    self._refresh_counts(connection, trace_id)
                    connection.execute(
                        """
                        INSERT INTO trace_persistence_status(trace_id,status,attempt_count,error_code,updated_at)
                        VALUES(?, 'persisted', 1, NULL, ?)
                        ON CONFLICT(trace_id) DO UPDATE SET
                            status='persisted', attempt_count=trace_persistence_status.attempt_count+1,
                            error_code=NULL, updated_at=excluded.updated_at
                        """,
                        (trace_id, now),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return applied

    def mark_integrity(self, trace_id: str, flag: str, *, dropped: int = 0) -> None:
        with suppress_observability(), self._connect() as connection:
            row = connection.execute(
                "SELECT integrity_flags_json FROM traces WHERE trace_id=?", (trace_id,)
            ).fetchone()
            if row is None:
                return
            flags = set(_loads(row[0], []))
            flags.add(flag)
            connection.execute(
                """
                UPDATE traces SET completeness='partial', integrity_flags_json=?,
                    dropped_record_count=dropped_record_count+? WHERE trace_id=?
                """,
                (_dumps(sorted(flags)), max(0, dropped), trace_id),
            )

    def abandon_running(self, *, older_than_seconds: float = 30.0) -> int:
        cutoff = (datetime.now(UTC) - timedelta(seconds=max(0, older_than_seconds))).isoformat()
        now = _now()
        with suppress_observability(), self._connect() as connection:
            pending_count = self._resolve_expired_pending(connection, now)
            rows = connection.execute(
                "SELECT trace_id,span_id,started_at FROM spans WHERE status='running' AND started_at<?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                duration = max(0.0, (datetime.fromisoformat(now) - datetime.fromisoformat(row[2])).total_seconds() * 1000)
                connection.execute(
                    """
                    UPDATE spans SET status='abandoned',ended_at=?,duration_ms=?,duration_estimated=1,
                        completion_status='process_crash' WHERE trace_id=? AND span_id=? AND status='running'
                    """,
                    (now, duration, row[0], row[1]),
                )
                self._mark_integrity_connection(connection, row[0], "process_crash")
                self._mark_integrity_connection(connection, row[0], "missing_span_end")
            traces = connection.execute(
                "SELECT trace_id,started_at FROM traces WHERE status='running' AND started_at<?", (cutoff,)
            ).fetchall()
            for row in traces:
                duration = max(0.0, (datetime.fromisoformat(now) - datetime.fromisoformat(row[1])).total_seconds() * 1000)
                connection.execute(
                    """
                    UPDATE traces SET status='abandoned',ended_at=?,duration_ms=?,duration_estimated=1,
                        completion_status='process_crash',completeness='partial' WHERE trace_id=? AND status='running'
                    """,
                    (now, duration, row[0]),
                )
                self._mark_integrity_connection(connection, row[0], "missing_root_end")
            return pending_count + len(rows) + len(traces)

    def list_traces(self, filters: TraceFilter, *, limit: int, offset: int = 0) -> list[TraceRecord]:
        clauses: list[str] = []
        params: list[object] = []
        mapping = {
            "status": filters.status,
            "trace_type": filters.trace_type,
            "repo_id": filters.repo_id,
            "index_version_id": filters.index_version_id,
            "run_id": filters.run_id,
            "error_code": filters.error_code,
        }
        for column, value in mapping.items():
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        if filters.start:
            clauses.append("started_at>=?")
            params.append(filters.start.isoformat())
        if filters.end:
            clauses.append("started_at<=?")
            params.append(filters.end.isoformat())
        if filters.min_duration_ms is not None:
            clauses.append("duration_ms>=?")
            params.append(filters.min_duration_ms)
        if filters.max_duration_ms is not None:
            clauses.append("duration_ms<=?")
            params.append(filters.max_duration_ms)
        if filters.component or filters.operation:
            span_parts: list[str] = ["spans.trace_id=traces.trace_id"]
            if filters.component:
                span_parts.append("spans.component=?")
                params.append(filters.component)
            if filters.operation:
                span_parts.append("spans.name=?")
                params.append(filters.operation)
            clauses.append(f"EXISTS(SELECT 1 FROM spans WHERE {' AND '.join(span_parts)})")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM traces{where} ORDER BY started_at DESC,trace_id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_trace_model(row) for row in rows]

    def get_trace(self, trace_id: str) -> TraceRecord:
        with suppress_observability(), self._connect() as connection:
            row = connection.execute("SELECT * FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
        if row is None:
            raise ObservabilityStoreError("trace_not_found", "Trace was not found.")
        return _trace_model(row)

    def list_spans(self, trace_id: str, *, limit: int = 2_000, offset: int = 0) -> list[SpanRecord]:
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM spans WHERE trace_id=? ORDER BY started_at,span_id LIMIT ? OFFSET ?",
                (trace_id, limit, offset),
            ).fetchall()
        return [_span_model(row) for row in rows]

    def get_span(self, trace_id: str, span_id: str) -> SpanRecord:
        with suppress_observability(), self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM spans WHERE trace_id=? AND span_id=?", (trace_id, span_id)
            ).fetchone()
        if row is None:
            raise ObservabilityStoreError("span_not_found", "Span was not found.")
        return _span_model(row)

    def list_events(
        self, trace_id: str, *, after_sequence: int = 0, limit: int = 500
    ) -> list[TraceEvent]:
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM span_events WHERE trace_id=? AND stream_sequence>?
                ORDER BY stream_sequence LIMIT ?
                """,
                (trace_id, after_sequence, limit),
            ).fetchall()
        return [_event_model(row) for row in rows]

    def event_sequence_bounds(self, trace_id: str) -> tuple[int | None, int | None]:
        with suppress_observability(), self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(stream_sequence),MAX(stream_sequence) FROM span_events WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
        return row[0], row[1]

    def list_links(self, trace_id: str) -> list[SpanLink]:
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM span_links WHERE trace_id=? ORDER BY rowid", (trace_id,)
            ).fetchall()
        output: list[SpanLink] = []
        for row in rows:
            data = dict(row)
            data["attributes"] = _loads(data.pop("attributes_json"), {})
            output.append(SpanLink.model_validate(data))
        return output

    def list_artifacts(self, trace_id: str) -> list[TraceArtifactRef]:
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trace_artifact_refs WHERE trace_id=? ORDER BY rowid", (trace_id,)
            ).fetchall()
        return [TraceArtifactRef(**dict(row)) for row in rows]

    def metrics_summary(self) -> dict[str, object]:
        with suppress_observability(), self._connect() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) total,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
                       SUM(CASE WHEN completeness!='complete' THEN 1 ELSE 0 END) incomplete,
                       AVG(duration_ms) average_duration_ms
                FROM traces
                """
            ).fetchone()
            by_type = connection.execute(
                "SELECT trace_type,COUNT(*) count FROM traces GROUP BY trace_type ORDER BY trace_type"
            ).fetchall()
        return {
            "total": totals["total"] or 0,
            "failed": totals["failed"] or 0,
            "incomplete": totals["incomplete"] or 0,
            "average_duration_ms": totals["average_duration_ms"],
            "by_type": {row["trace_type"]: row["count"] for row in by_type},
            "telemetry_complete": not bool(totals["incomplete"]),
        }

    def metrics_timeseries(
        self, start: datetime, end: datetime, *, bucket_seconds: int
    ) -> list[dict[str, object]]:
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                """
                SELECT CAST(strftime('%s',started_at)/? AS INTEGER)*? bucket_epoch,
                       COUNT(*) count,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
                       SUM(CASE WHEN completeness!='complete' THEN 1 ELSE 0 END) incomplete,
                       AVG(duration_ms) average_duration_ms
                FROM traces
                WHERE started_at>=? AND started_at<=?
                GROUP BY bucket_epoch ORDER BY bucket_epoch
                """,
                (bucket_seconds, bucket_seconds, start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            {
                "timestamp": datetime.fromtimestamp(row["bucket_epoch"], UTC).isoformat(),
                "count": row["count"],
                "failed": row["failed"] or 0,
                "incomplete": row["incomplete"] or 0,
                "average_duration_ms": row["average_duration_ms"],
                "telemetry_complete": not bool(row["incomplete"]),
            }
            for row in rows
        ]

    def delete_before(self, cutoff: datetime, *, limit: int = 500) -> int:
        with suppress_observability(), self._connect() as connection:
            rows = connection.execute(
                """
                SELECT trace_id FROM traces
                WHERE ended_at IS NOT NULL AND ended_at<? AND retention_hold=0
                  AND NOT EXISTS(
                    SELECT 1 FROM trace_export_jobs jobs
                    WHERE jobs.trace_id=traces.trace_id AND jobs.status IN ('queued','exporting')
                  )
                LIMIT ?
                """,
                (cutoff.isoformat(), limit),
            ).fetchall()
            for row in rows:
                connection.execute("DELETE FROM traces WHERE trace_id=?", (row[0],))
            return len(rows)

    def _apply_one(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        handlers = {
            "trace_start": self._trace_start,
            "span_start": self._span_start,
            "span_event": self._span_event,
            "span_link": self._span_link,
            "artifact_ref": self._artifact_ref,
            "span_end": self._span_end,
            "trace_end": self._trace_end,
        }
        handlers[command.command_type](connection, command)

    def _trace_start(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        connection.execute(
            """
            INSERT OR IGNORE INTO traces(
                trace_id,trace_type,root_span_id,request_id,run_id,task_id,repo_id,index_version_id,
                caller_scope_hash,status,lifecycle_version,last_command_id,started_at,recording_mode,
                diagnostic_sampled,otlp_sampled,completeness,attribute_registry_version,
                operation_taxonomy_version,semantic_convention_version,hash_key_id,hash_algorithm,
                attributes_json
            ) VALUES(?,?,?,?,?,?,?,?,?,'running',1,?,?,?, ?,?,'unknown',?,?,?,?,?,?)
            """,
            (
                command.trace_id, payload["trace_type"], payload["root_span_id"],
                payload.get("request_id"), payload.get("run_id"), payload.get("task_id"),
                payload.get("repo_id"), payload.get("index_version_id"),
                payload.get("caller_scope_hash"), command.command_id, command.occurred_at.isoformat(),
                payload.get("recording_mode", "metadata"), int(payload.get("diagnostic_sampled", False)),
                int(payload.get("otlp_sampled", False)), payload.get("attribute_registry_version", "cra-attributes-v1"),
                payload.get("operation_taxonomy_version", "cra-operations-v1"),
                payload.get("semantic_convention_version"), payload.get("hash_key_id"),
                payload.get("hash_algorithm"), _dumps(payload.get("attributes", {})),
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO trace_persistence_status(
                trace_id,status,attempt_count,error_code,updated_at
            ) VALUES(?, 'persisting', 0, NULL, ?)
            """,
            (command.trace_id, _now()),
        )

    def _span_start(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        connection.execute(
            """
            INSERT OR IGNORE INTO spans(
                trace_id,span_id,parent_span_id,name,component,kind,status,lifecycle_version,
                last_command_id,started_at,attributes_json
            ) VALUES(?,?,?,?,?,?,'running',?,?,?,?)
            """,
            (
                command.trace_id, command.span_id, payload.get("parent_span_id"), payload["name"],
                payload["component"], payload.get("kind", "internal"), command.lifecycle_sequence,
                command.command_id, command.occurred_at.isoformat(), _dumps(payload.get("attributes", {})),
            ),
        )
        pending = connection.execute(
            "SELECT * FROM pending_span_terminals WHERE trace_id=? AND span_id=? ORDER BY lifecycle_sequence LIMIT 1",
            (command.trace_id, command.span_id),
        ).fetchone()
        if pending:
            synthetic = TelemetryCommand(
                command_id=pending["command_id"], command_type="span_end",
                trace_id=pending["trace_id"], span_id=pending["span_id"],
                lifecycle_sequence=pending["lifecycle_sequence"], occurred_at=datetime.now(UTC),
                payload=_loads(pending["payload_json"], {}),
            )
            self._apply_span_terminal(connection, synthetic)
            connection.execute("DELETE FROM pending_span_terminals WHERE command_id=?", (pending["command_id"],))

    def _span_end(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        exists = connection.execute(
            "SELECT status FROM spans WHERE trace_id=? AND span_id=?",
            (command.trace_id, command.span_id),
        ).fetchone()
        if exists is None:
            connection.execute(
                """
                INSERT OR REPLACE INTO pending_span_terminals(
                    command_id,trace_id,span_id,lifecycle_sequence,occurred_at,payload_json,expires_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    command.command_id, command.trace_id, command.span_id,
                    command.lifecycle_sequence, command.occurred_at.isoformat(),
                    _dumps(command.payload),
                    (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                ),
            )
            return
        self._apply_span_terminal(connection, command)

    def _resolve_expired_pending(self, connection: sqlite3.Connection, now: str) -> int:
        rows = connection.execute(
            "SELECT * FROM pending_span_terminals WHERE expires_at<=?", (now,)
        ).fetchall()
        for row in rows:
            payload = _loads(row["payload_json"], {})
            connection.execute(
                """
                INSERT OR IGNORE INTO spans(
                    trace_id,span_id,parent_span_id,name,component,kind,status,lifecycle_version,
                    last_command_id,completion_status,started_at,ended_at,duration_ms,
                    duration_estimated,attributes_json,error_code,exception_type,
                    error_message_template,error_message_hash
                ) VALUES(?,?,NULL,'telemetry.missing_start','database','internal',?,?,?,?,?,?,?,1,'{}',?,?,?,?)
                """,
                (
                    row["trace_id"], row["span_id"], payload.get("status", "abandoned"),
                    row["lifecycle_sequence"], row["command_id"],
                    payload.get("completion_status") or "missing_span_start",
                    row["occurred_at"], row["occurred_at"],
                    payload.get("duration_ms"), payload.get("error_code"),
                    payload.get("exception_type"), payload.get("error_message_template"),
                    payload.get("error_message_hash"),
                ),
            )
            self._mark_integrity_connection(connection, row["trace_id"], "missing_span_start")
            self._mark_integrity_connection(connection, row["trace_id"], "orphan_span")
            connection.execute(
                "DELETE FROM pending_span_terminals WHERE command_id=?", (row["command_id"],)
            )
        return len(rows)

    def _apply_span_terminal(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        changed = connection.execute(
            """
            UPDATE spans SET status=?,lifecycle_version=?,last_command_id=?,completion_status=?,
                ended_at=?,duration_ms=?,duration_estimated=?,error_code=?,exception_type=?,
                error_message_template=?,error_message_hash=?
            WHERE trace_id=? AND span_id=? AND status='running' AND lifecycle_version<=?
            """,
            (
                payload["status"], command.lifecycle_sequence, command.command_id,
                payload.get("completion_status"), command.occurred_at.isoformat(),
                payload.get("duration_ms"), int(payload.get("duration_estimated", False)),
                payload.get("error_code"), payload.get("exception_type"),
                payload.get("error_message_template"), payload.get("error_message_hash"),
                command.trace_id, command.span_id, command.lifecycle_sequence,
            ),
        ).rowcount
        if not changed:
            row = connection.execute(
                "SELECT status,last_command_id FROM spans WHERE trace_id=? AND span_id=?",
                (command.trace_id, command.span_id),
            ).fetchone()
            if row and row["last_command_id"] != command.command_id:
                self._mark_integrity_connection(connection, command.trace_id, "store_failure")

    def _trace_end(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        row = connection.execute(
            "SELECT status,integrity_flags_json,root_span_id FROM traces WHERE trace_id=?",
            (command.trace_id,),
        ).fetchone()
        if row is None:
            return
        if row["status"] != "running":
            return
        flags = set(_loads(row["integrity_flags_json"], []))
        running = connection.execute(
            "SELECT COUNT(*) FROM spans WHERE trace_id=? AND status='running'", (command.trace_id,)
        ).fetchone()[0]
        if running:
            flags.add("missing_span_end")
        orphan = connection.execute(
            """
            SELECT COUNT(*) FROM spans child
            WHERE child.trace_id=? AND child.span_id<>? AND child.parent_span_id IS NOT NULL
              AND NOT EXISTS(
                SELECT 1 FROM spans parent
                WHERE parent.trace_id=child.trace_id AND parent.span_id=child.parent_span_id
              )
            """,
            (command.trace_id, row["root_span_id"]),
        ).fetchone()[0]
        if orphan:
            flags.add("orphan_span")
        sequence = connection.execute(
            "SELECT COUNT(*),MIN(stream_sequence),MAX(stream_sequence) FROM span_events WHERE trace_id=?",
            (command.trace_id,),
        ).fetchone()
        if sequence[0] and sequence[2] - sequence[1] + 1 != sequence[0]:
            flags.add("sequence_gap")
        if flags:
            connection.execute(
                "UPDATE traces SET integrity_flags_json=? WHERE trace_id=?",
                (_dumps(sorted(flags)), command.trace_id),
            )
        completeness = "complete" if not flags else "partial"
        connection.execute(
            """
            UPDATE traces SET status=?,lifecycle_version=?,last_command_id=?,completion_status=?,
                ended_at=?,duration_ms=?,duration_estimated=?,completeness=?,error_code=?
            WHERE trace_id=? AND status='running'
            """,
            (
                payload["status"], command.lifecycle_sequence, command.command_id,
                payload.get("completion_status"), command.occurred_at.isoformat(),
                payload.get("duration_ms"), int(payload.get("duration_estimated", False)),
                completeness, payload.get("error_code"), command.trace_id,
            ),
        )

    def _span_event(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        if connection.execute(
            "SELECT 1 FROM span_events WHERE trace_id=? AND event_id=?",
            (command.trace_id, payload["event_id"]),
        ).fetchone() is not None:
            return
        sequence = self._allocate_sequence(connection, command.trace_id)
        connection.execute(
            """
            INSERT OR IGNORE INTO span_events(
                trace_id,event_id,span_id,producer_sequence,stream_sequence,name,severity,
                occurred_at,attributes_json,size_bytes
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                command.trace_id, payload["event_id"], command.span_id,
                payload.get("producer_sequence"), sequence, payload["name"],
                payload.get("severity", "info"), command.occurred_at.isoformat(),
                _dumps(payload.get("attributes", {})), payload.get("size_bytes", 0),
            ),
        )

    def _span_link(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        connection.execute(
            """
            INSERT OR IGNORE INTO span_links(
                link_id,trace_id,span_id,linked_trace_id,linked_span_id,relation,attributes_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                payload["link_id"], command.trace_id, command.span_id,
                payload["linked_trace_id"], payload.get("linked_span_id"),
                payload["relation"], _dumps(payload.get("attributes", {})),
            ),
        )

    def _artifact_ref(self, connection: sqlite3.Connection, command: TelemetryCommand) -> None:
        payload = command.payload
        connection.execute(
            """
            INSERT OR IGNORE INTO trace_artifact_refs(
                ref_id,trace_id,span_id,artifact_type,artifact_id,content_hash,repo_id,
                index_version_id,role
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["ref_id"], command.trace_id, command.span_id,
                payload["artifact_type"], payload["artifact_id"], payload.get("content_hash"),
                payload.get("repo_id"), payload.get("index_version_id"), payload["role"],
            ),
        )

    def _allocate_sequence(self, connection: sqlite3.Connection, trace_id: str) -> int:
        row = connection.execute(
            "SELECT next_sequence FROM trace_stream_sequences WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if row is None:
            sequence = 1
            connection.execute(
                "INSERT INTO trace_stream_sequences(trace_id,next_sequence,updated_at) VALUES(?,?,?)",
                (trace_id, 2, _now()),
            )
        else:
            sequence = row["next_sequence"]
            connection.execute(
                "UPDATE trace_stream_sequences SET next_sequence=?,updated_at=? WHERE trace_id=?",
                (sequence + 1, _now(), trace_id),
            )
        return sequence

    def _refresh_counts(self, connection: sqlite3.Connection, trace_id: str) -> None:
        span_count = connection.execute(
            "SELECT COUNT(*) FROM spans WHERE trace_id=?", (trace_id,)
        ).fetchone()[0]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM span_events WHERE trace_id=?", (trace_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE traces SET span_count=?,event_count=? WHERE trace_id=?",
            (span_count, event_count, trace_id),
        )

    def _mark_integrity_connection(
        self, connection: sqlite3.Connection, trace_id: str, flag: str
    ) -> None:
        row = connection.execute(
            "SELECT integrity_flags_json FROM traces WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if row is None:
            return
        flags = set(_loads(row[0], []))
        flags.add(flag)
        connection.execute(
            "UPDATE traces SET completeness='partial',integrity_flags_json=? WHERE trace_id=?",
            (_dumps(sorted(flags)), trace_id),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection


def _trace_model(row: sqlite3.Row) -> TraceRecord:
    data = dict(row)
    data["attributes"] = _loads(data.pop("attributes_json"), {})
    data["integrity_flags"] = _loads(data.pop("integrity_flags_json"), [])
    for key in ("duration_estimated", "diagnostic_sampled", "otlp_sampled", "retention_hold"):
        data[key] = bool(data[key])
    return TraceRecord.model_validate(data)


def _span_model(row: sqlite3.Row) -> SpanRecord:
    data = dict(row)
    data["attributes"] = _loads(data.pop("attributes_json"), {})
    data["duration_estimated"] = bool(data["duration_estimated"])
    return SpanRecord.model_validate(data)


def _event_model(row: sqlite3.Row) -> TraceEvent:
    data = dict(row)
    data["attributes"] = _loads(data.pop("attributes_json"), {})
    return TraceEvent.model_validate(data)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def _now() -> str:
    return datetime.now(UTC).isoformat()
