from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .schemas import ProviderReservation
from .store import ControlPlaneError, LocalControlPlaneStore


class ProviderReservationService:
    """Authoritative local ledger; Team uses the same operations in PostgreSQL."""

    def __init__(self, store: LocalControlPlaneStore) -> None:
        self.store = store

    def reserve(
        self, *, workspace_id: str, project_id: str | None, provider_profile_id: str,
        model_id: str, job_id: str, attempt_id: str, estimated_tokens: int,
        estimated_cost: float | None, lease_seconds: int = 120,
    ) -> ProviderReservation:
        now = datetime.now(UTC)
        reservation = ProviderReservation(
            reservation_id=f"provider_reservation_{uuid4().hex}",
            workspace_id=workspace_id, project_id=project_id,
            provider_profile_id=provider_profile_id, model_id=model_id,
            job_id=job_id, attempt_id=attempt_id, estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost, lease_until=now + timedelta(seconds=lease_seconds),
            status="reserved", created_at=now, updated_at=now,
        )
        self.store.migrate()
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO provider_reservations VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    reservation.reservation_id, workspace_id, job_id, attempt_id,
                    reservation.status, reservation.lease_until.isoformat(),
                    reservation.model_dump_json(), now.isoformat(), now.isoformat(),
                ),
            )
        return reservation

    def settle(
        self, reservation_id: str, *, actual_tokens: int, actual_cost: float | None,
    ) -> ProviderReservation:
        return self._finish(reservation_id, "settled", actual_tokens, actual_cost)

    def release(self, reservation_id: str) -> ProviderReservation:
        return self._finish(reservation_id, "released", None, None)

    def recover_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        recovered = 0
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT reservation_id,reservation_json FROM provider_reservations WHERE status='reserved' AND lease_until<?",
                (now.isoformat(),),
            ).fetchall()
            for row in rows:
                reservation = ProviderReservation.model_validate_json(row["reservation_json"])
                updated = reservation.model_copy(update={"status": "expired", "updated_at": now})
                connection.execute(
                    "UPDATE provider_reservations SET status='expired',reservation_json=?,updated_at=? WHERE reservation_id=?",
                    (updated.model_dump_json(), now.isoformat(), reservation.reservation_id),
                )
                recovered += 1
            connection.commit()
        return recovered

    def _finish(
        self, reservation_id: str, status: str, actual_tokens: int | None,
        actual_cost: float | None,
    ) -> ProviderReservation:
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT reservation_json FROM provider_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise ControlPlaneError("provider_reservation_not_found")
            reservation = ProviderReservation.model_validate_json(row[0])
            if reservation.status != "reserved":
                raise ControlPlaneError("provider_reservation_terminal")
            updated = reservation.model_copy(update={
                "status": status, "actual_tokens": actual_tokens,
                "actual_cost": actual_cost, "updated_at": now,
            })
            connection.execute(
                "UPDATE provider_reservations SET status=?,reservation_json=?,updated_at=? WHERE reservation_id=?",
                (status, updated.model_dump_json(), now.isoformat(), reservation_id),
            )
            connection.commit()
        return updated

