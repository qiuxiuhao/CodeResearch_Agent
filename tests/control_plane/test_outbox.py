from __future__ import annotations

from backend.app.control_plane.outbox import OutboxDispatcher
from backend.app.control_plane.store import LocalControlPlaneStore, message_deduplication_key


def _store(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    created = store.create_job(
        workspace_id="w", project_id="p", job_type="analysis", queue_name="cra.analysis",
        request={"id": "a"}, idempotency_key="unique-key", actor_id_hash="actor",
    )
    return store, created


class Publisher:
    def __init__(self, store):
        self.store = store
        self.transaction_active_during_publish = None

    def publish(self, **kwargs):
        self.kwargs = kwargs
        with self.store._connect() as connection:
            self.transaction_active_during_publish = connection.in_transaction
        return "message-1"


def test_outbox_network_publish_occurs_outside_database_transaction(tmp_path):
    store, _ = _store(tmp_path)
    publisher = Publisher(store)
    assert OutboxDispatcher(store, publisher, "dispatcher").dispatch_once() == 1
    assert publisher.transaction_active_during_publish is False
    assert publisher.kwargs["queue_name"] == "cra.analysis"


def test_outbox_expired_claim_is_recovered(tmp_path):
    store, _ = _store(tmp_path)
    first = store.claim_outbox("one", lease_seconds=-1)
    second = store.claim_outbox("two")
    assert first[0].event.outbox_event_id == second[0].event.outbox_event_id
    assert first[0].claim_token != second[0].claim_token


def test_publish_success_before_crash_can_duplicate_safely(tmp_path):
    store, _ = _store(tmp_path)
    first = store.claim_outbox("one", lease_seconds=-1)[0]
    second = store.claim_outbox("two")[0]
    assert first.event.message_deduplication_key == second.event.message_deduplication_key


def test_two_dispatchers_cannot_own_same_claim(tmp_path):
    store, _ = _store(tmp_path)
    assert len(store.claim_outbox("one")) == 1
    assert store.claim_outbox("two") == []


def test_message_deduplication_key_is_stable():
    left = message_deduplication_key("j", 2, 1, "r")
    right = message_deduplication_key("j", 2, 1, "r")
    assert left == right
    assert len(left) == 64


def test_publish_failure_releases_claim_for_retry(tmp_path):
    store, created = _store(tmp_path)

    class BrokenPublisher:
        def publish(self, **kwargs):
            raise OSError("broker unavailable")

    assert OutboxDispatcher(store, BrokenPublisher(), "dispatcher").dispatch_once() == 0
    with store._connect() as connection:
        row = connection.execute(
            "SELECT outbox_json FROM outbox_events WHERE attempt_id=?", (created.attempt.attempt_id,)
        ).fetchone()
    from backend.app.control_plane.schemas import OutboxEvent
    event = OutboxEvent.model_validate_json(row[0])
    assert event.status == "pending"
    assert event.claim_token_hash is None
    assert event.last_publish_error_code == "broker_publish_failed"
