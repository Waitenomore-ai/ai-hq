from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from ai_hq.recovery.models import (
    RecoveryIncident,
    RecoveryStatus,
    RecoveryStatusResult,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _bounded_status_code(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 100 <= value <= 599 else None


class RecoveryStatusService:
    """Persist only the latest bounded operator-facing recovery status."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _active_incident(db, target: str) -> RecoveryIncident | None:
        return db.scalar(
            select(RecoveryIncident)
            .where(
                RecoveryIncident.target == target,
                RecoveryIncident.active_key.is_not(None),
            )
            .order_by(
                RecoveryIncident.last_observed_at.desc(),
                RecoveryIncident.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _incident_projection(incident: RecoveryIncident | None) -> tuple[str | None, Any, int]:
        if incident is None:
            return None, None, 0
        return incident.id, incident.state, int(incident.consecutive_failures)

    def record_successful_cycle(
        self,
        *,
        target: str,
        observed_at: datetime,
        summary: Mapping[str, Any],
    ) -> dict:
        reachable = _bounded_bool(summary.get("reachable"))
        status_code = _bounded_status_code(summary.get("status_code"))
        ready = _bounded_bool(summary.get("ready"))

        with self.session_factory() as db:
            incident = self._active_incident(db, target)
            incident_id, incident_state, consecutive_failures = self._incident_projection(incident)

            if ready is False or incident is not None:
                result = RecoveryStatusResult.UNHEALTHY
            elif ready is True:
                result = RecoveryStatusResult.HEALTHY
            else:
                result = RecoveryStatusResult.UNKNOWN

            row = db.get(RecoveryStatus, target)
            if row is None:
                row = RecoveryStatus(target=target)
                db.add(row)

            row.last_probe_at = _utc(observed_at)
            row.last_result = result
            row.reachable = reachable
            row.status_code = status_code
            row.ready = ready
            row.consecutive_failures = consecutive_failures
            row.active_incident_id = incident_id
            row.active_incident_state = incident_state
            db.commit()

        return self.snapshot(target)

    def record_cycle_error(
        self,
        *,
        target: str,
        observed_at: datetime,
    ) -> dict:
        with self.session_factory() as db:
            incident = self._active_incident(db, target)
            incident_id, incident_state, consecutive_failures = self._incident_projection(incident)

            row = db.get(RecoveryStatus, target)
            if row is None:
                row = RecoveryStatus(target=target)
                db.add(row)

            row.last_probe_at = _utc(observed_at)
            row.last_result = RecoveryStatusResult.ERROR
            row.reachable = None
            row.status_code = None
            row.ready = None
            row.consecutive_failures = consecutive_failures
            row.active_incident_id = incident_id
            row.active_incident_state = incident_state
            db.commit()

        return self.snapshot(target)

    def snapshot(self, target: str) -> dict:
        with self.session_factory() as db:
            row = db.get(RecoveryStatus, target)
            if row is None:
                return {
                    "last_probe_at": None,
                    "last_result": "unknown",
                    "reachable": None,
                    "status_code": None,
                    "ready": None,
                    "consecutive_failures": 0,
                    "active_incident_id": None,
                    "active_incident_state": None,
                }

            return {
                "last_probe_at": _utc(row.last_probe_at),
                "last_result": row.last_result.value,
                "reachable": row.reachable,
                "status_code": row.status_code,
                "ready": row.ready,
                "consecutive_failures": int(row.consecutive_failures),
                "active_incident_id": row.active_incident_id,
                "active_incident_state": (
                    row.active_incident_state.value
                    if row.active_incident_state is not None
                    else None
                ),
            }
