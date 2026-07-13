from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ReservationResult:
    allowed: bool
    reserved: int = 0
    reservation_id: str | None = None
    reason: str | None = None


class BudgetManager:
    """Task-scoped counters with atomic reservations for concurrent callers."""

    def __init__(self, max_total_entities: int, max_provider_requests: int) -> None:
        self.max_total_entities = max_total_entities
        self.max_provider_requests = max_provider_requests
        self._lock = Lock()
        self._selected_entities = 0
        self._entities_by_type: dict[str, int] = {}
        self._reserved_provider_requests = 0
        self._sent_provider_requests = 0
        self._successful_provider_requests = 0
        self._cache_hits = 0
        self._skipped = 0
        self._retries = 0
        self._fallbacks = 0
        self._reservations: dict[str, str] = {}

    def try_reserve_entities(self, task_type: str, count: int, *, reserve_for_future: int = 0) -> ReservationResult:
        if count <= 0:
            return ReservationResult(True, 0)
        with self._lock:
            available = max(0, self.max_total_entities - self._selected_entities - reserve_for_future)
            reserved = min(count, available)
            self._selected_entities += reserved
            self._entities_by_type[task_type] = self._entities_by_type.get(task_type, 0) + reserved
            if reserved < count:
                self._skipped += count - reserved
            return ReservationResult(reserved > 0, reserved, reason=None if reserved == count else "entity_budget_exceeded")

    def try_reserve_provider_request(
        self, provider: str, task_type: str, context_id: str, *, retry: bool = False, fallback: bool = False
    ) -> ReservationResult:
        with self._lock:
            if self._reserved_provider_requests >= self.max_provider_requests:
                return ReservationResult(False, reason="provider_request_budget_exceeded")
            reservation_id = uuid4().hex
            self._reserved_provider_requests += 1
            self._reservations[reservation_id] = f"{provider}:{task_type}:{context_id}"
            if retry:
                self._retries += 1
            if fallback:
                self._fallbacks += 1
            return ReservationResult(True, 1, reservation_id)

    def record_request_result(self, reservation_id: str | None, outcome: str) -> None:
        if not reservation_id:
            return
        with self._lock:
            if reservation_id not in self._reservations:
                return
            self._reservations.pop(reservation_id)
            self._sent_provider_requests += 1
            if outcome == "success":
                self._successful_provider_requests += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def record_skipped(self, count: int = 1) -> None:
        with self._lock:
            self._skipped += count

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "max_total_entities": self.max_total_entities,
                "selected_entities": self._selected_entities,
                "entities_by_type": dict(self._entities_by_type),
                "max_provider_requests": self.max_provider_requests,
                "reserved_provider_requests": self._reserved_provider_requests,
                "sent_provider_requests": self._sent_provider_requests,
                "successful_provider_requests": self._successful_provider_requests,
                "cache_hits": self._cache_hits,
                "skipped": self._skipped,
                "retries": self._retries,
                "fallbacks": self._fallbacks,
            }
