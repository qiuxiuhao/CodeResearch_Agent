from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass

from .celery_worker import TaskEnvelope
from .config import PlatformSettings


@dataclass(slots=True)
class TeamWorker:
    database_url: str
    worker_id: str
    worker_version: str = "2.0.0"

    @classmethod
    def from_env(cls) -> "TeamWorker":
        settings = PlatformSettings.from_env()
        return cls(
            settings.control_database_url,
            f"{socket.gethostname()}:{os.getpid()}",
            os.getenv("CRA_WORKER_VERSION", "2.0.0"),
        )

    def execute(self, envelope: TaskEnvelope, *, celery_task_id: str | None) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("team worker requires psycopg") from exc
        worker_hash = self.register()
        queue_name = self._queue_for(envelope)
        capabilities = {
            "job_id": envelope.job_id,
            "attempt_id": envelope.attempt_id,
            "job_type": envelope.job_type,
        }
        # The message cannot grant access. It only narrows the authoritative DB claim to the
        # immutable job/attempt identity carried by this wake-up message.
        with psycopg.connect(self.database_url, autocommit=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM cra_control.claim_next_job(%s,%s,%s::jsonb,%s)",
                    (self.worker_id, self.worker_version, json.dumps(capabilities), [queue_name]),
                )
                claim = cursor.fetchone()
            connection.commit()
        if claim is None:
            return
        if str(claim[0]) != envelope.job_id or str(claim[3]) != envelope.attempt_id:
            raise RuntimeError("authoritative_claim_identity_mismatch")
        # Domain handler migration is intentionally explicit; missing handlers become terminal
        # control-plane errors rather than executing arbitrary payloads from the broker.
        from .team_worker_handlers import execute_claimed_job

        execute_claimed_job(
            database_url=self.database_url,
            claim=claim,
            worker_id_hash=worker_hash,
            celery_task_id=celery_task_id,
        )

    def register(self) -> str:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("team worker requires psycopg") from exc
        worker_hash = hashlib.sha256(self.worker_id.encode()).hexdigest()
        queues = self.registered_queues()
        capabilities = {
            "supported_job_types": [item.removeprefix("cra.") for item in queues],
            "handler_version": "1",
        }
        minimum = int(os.getenv("CRA_MIN_TASK_SCHEMA_VERSION", "1"))
        maximum = int(os.getenv("CRA_MAX_TASK_SCHEMA_VERSION", "1"))
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """INSERT INTO cra_control.worker_registry(
                     worker_id_hash,worker_version,min_task_schema_version,
                     max_task_schema_version,capabilities,queue_names,heartbeat_at
                   ) VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,clock_timestamp())
                   ON CONFLICT(worker_id_hash) DO UPDATE SET
                     worker_version=excluded.worker_version,
                     min_task_schema_version=excluded.min_task_schema_version,
                     max_task_schema_version=excluded.max_task_schema_version,
                     capabilities=excluded.capabilities,queue_names=excluded.queue_names,
                     heartbeat_at=excluded.heartbeat_at""",
                (
                    worker_hash, self.worker_version, minimum, maximum,
                    json.dumps(capabilities), json.dumps(queues),
                ),
            )
            connection.commit()
        return worker_hash

    @staticmethod
    def registered_queues() -> list[str]:
        value = os.getenv("CRA_WORKER_QUEUES") or os.getenv("CRA_WORKER_QUEUE")
        if value:
            return sorted({item.strip() for item in value.split(",") if item.strip()})
        return [
            "cra.analysis", "cra.indexing", "cra.research", "cra.alignment",
            "cra.evaluation", "cra.replay", "cra.export", "cra.backup", "cra.restore",
            "cra.maintenance",
        ]

    @staticmethod
    def _queue_for(_envelope: TaskEnvelope) -> str:
        return os.getenv("CRA_WORKER_QUEUE", f"cra.{_envelope.job_type}")
