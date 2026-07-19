from __future__ import annotations

from typing import Protocol

from .store import LocalControlPlaneStore


class MessagePublisher(Protocol):
    def publish(
        self, *, payload: dict, queue_name: str, deduplication_key: str,
        task_schema_version: int,
    ) -> str: ...


class OutboxDispatcher:
    """Claim and acknowledgement are transactions; publish is intentionally between them."""

    def __init__(self, store: LocalControlPlaneStore, publisher: MessagePublisher, dispatcher_id: str) -> None:
        self.store = store
        self.publisher = publisher
        self.dispatcher_id = dispatcher_id

    def dispatch_once(self, batch_size: int = 10) -> int:
        claims = self.store.claim_outbox(self.dispatcher_id, batch_size=batch_size)
        published = 0
        for claim in claims:
            event = claim.event
            try:
                message_id = self.publisher.publish(
                    payload=event.payload,
                    queue_name=_queue_for_event(event.payload),
                    deduplication_key=event.message_deduplication_key,
                    task_schema_version=event.task_schema_version,
                )
            except Exception:
                self.store.mark_outbox_publish_failed(
                    event.outbox_event_id, claim.claim_token, "broker_publish_failed",
                )
            else:
                self.store.mark_outbox_published(
                    event.outbox_event_id, claim.claim_token, message_id,
                )
                published += 1
        return published


def _queue_for_event(payload: dict) -> str:
    job_type = str(payload.get("job_type") or "maintenance")
    allowed = {
        "analysis", "indexing", "research", "alignment", "evaluation", "replay",
        "export", "backup", "restore", "maintenance", "delete",
    }
    return f"cra.{job_type}" if job_type in allowed else "cra.maintenance"
