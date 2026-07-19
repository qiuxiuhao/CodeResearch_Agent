from __future__ import annotations

import argparse
import os
import time
from datetime import UTC, datetime

from .celery_app import build_celery_app
from .config import PlatformSettings


def run_dispatcher() -> None:
    import psycopg

    settings = PlatformSettings.from_env()
    celery = build_celery_app(settings)
    dispatcher_id = f"dispatcher:{os.getpid()}"
    while True:
        with psycopg.connect(settings.control_database_url) as connection:
            rows = connection.execute(
                "SELECT * FROM cra_control.claim_outbox_batch(%s,%s,%s,%s)",
                (dispatcher_id, 1, 1, 50),
            ).fetchall()
            connection.commit()
        for row in rows:
            event_id, job_id, attempt_id, schema, dedup, claim_token, payload = row
            envelope = dict(payload)
            envelope["message_deduplication_key"] = dedup
            result = celery.send_task(
                "cra.execute_job", args=[envelope], queue=_queue_for_payload(envelope),
                headers={"message_deduplication_key": dedup},
            )
            with psycopg.connect(settings.control_database_url) as connection:
                acknowledged = connection.execute(
                    "SELECT cra_control.acknowledge_outbox_publish(%s,%s,%s)",
                    (event_id, claim_token, result.id),
                ).fetchone()[0]
                connection.commit()
            if not acknowledged:
                continue
        time.sleep(0.25 if rows else 1.0)


def run_beat() -> None:
    import psycopg

    settings = PlatformSettings.from_env()
    while True:
        window = datetime.now(UTC).replace(second=0, microsecond=0)
        with psycopg.connect(settings.control_database_url) as connection:
            connection.execute(
                "SELECT cra_control.claim_periodic_window(%s,%s,%s,%s)",
                ("maintenance-minute", window, "maintenance", "global"),
            )
            connection.commit()
        time.sleep(30)


def _queue_for_payload(payload: dict) -> str:
    job_type = str(payload.get("job_type") or "analysis")
    return f"cra.{job_type}" if job_type in {
        "analysis", "indexing", "research", "alignment", "evaluation", "replay", "export",
        "backup", "restore", "maintenance",
    } else "cra.maintenance"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("process", choices=("dispatcher", "beat"))
    args = parser.parse_args(argv)
    run_dispatcher() if args.process == "dispatcher" else run_beat()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
