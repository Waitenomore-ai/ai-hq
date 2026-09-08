from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_hq.config import OperatingMode, Settings
from ai_hq.recovery.models import RecoveryAttempt, RecoveryIncident, RecoveryIncidentState
from ai_hq.recovery.status import RecoveryStatusService


SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]

_TARGET = "dripvid"
_COMPONENT = "app"
_ACTIVE_KEY = "dripvid:app"
_FRESH_HEALTHY_SECONDS = 5
_DRILL_DIAGNOSTICS = {"drill": True}
_UNHEALTHY_SUMMARY = {
    "reachable": True,
    "status_code": 503,
    "ready": False,
    "incident_detected": True,
    "incident_resolved": False,
    "worked": True,
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _failure(code: str) -> dict[str, object]:
    return {"ok": False, "code": code}


class RecoveryDrillService:
    """Inject one fixed observe-only recovery incident for operator verification."""

    def __init__(self, session_factory: SessionFactory, *, clock: Clock | None = None) -> None:
        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return _utc(self.clock())

    def _has_active_incident(self) -> bool | None:
        try:
            with self.session_factory() as db:
                active = db.scalar(
                    select(RecoveryIncident.id)
                    .where(
                        RecoveryIncident.target == _TARGET,
                        RecoveryIncident.active_key.is_not(None),
                    )
                    .limit(1)
                )
                return active is not None
        except Exception:
            return None

    def _fresh_healthy_snapshot(self, now: datetime) -> tuple[bool, str | None]:
        try:
            snapshot = RecoveryStatusService(self.session_factory).snapshot(_TARGET)
        except Exception:
            return False, "drill_failed"

        if (
            snapshot.get("last_result") != "healthy"
            or snapshot.get("ready") is not True
            or snapshot.get("active_incident_id") is not None
            or snapshot.get("active_incident_state") is not None
        ):
            return False, "healthy_status_required"

        last_probe_at = snapshot.get("last_probe_at")
        if not isinstance(last_probe_at, datetime):
            return False, "fresh_healthy_probe_required"

        age = now - _utc(last_probe_at)
        if age.total_seconds() < 0 or age.total_seconds() > _FRESH_HEALTHY_SECONDS:
            return False, "fresh_healthy_probe_required"

        return True, None

    def _insert_incident(self, *, now: datetime, threshold: int) -> RecoveryIncident | dict[str, object]:
        try:
            with self.session_factory() as db:
                active = db.scalar(
                    select(RecoveryIncident)
                    .where(
                        RecoveryIncident.target == _TARGET,
                        RecoveryIncident.active_key.is_not(None),
                    )
                    .limit(1)
                )
                if active is not None:
                    return _failure("active_incident_present")

                incident = RecoveryIncident(
                    active_key=_ACTIVE_KEY,
                    target=_TARGET,
                    component=_COMPONENT,
                    state=RecoveryIncidentState.SUSPECT,
                    consecutive_failures=threshold,
                    first_failure_at=now,
                    last_failure_at=now,
                    last_observed_at=now,
                    diagnostics=dict(_DRILL_DIAGNOSTICS),
                    verification={},
                    recovery_mission_id=None,
                )
                db.add(incident)
                db.commit()
                db.refresh(incident)
                return incident
        except IntegrityError:
            return _failure("drill_conflict")
        except Exception:
            return _failure("drill_failed")

    def _verify_no_mutation_artifacts(self, incident_id: str) -> bool:
        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None or incident.recovery_mission_id is not None:
                    return False

                attempt_count = db.scalar(
                    select(func.count(RecoveryAttempt.id)).where(
                        RecoveryAttempt.incident_id == incident_id
                    )
                )
                return int(attempt_count or 0) == 0
        except Exception:
            return False

    def run(self, *, settings: Settings) -> dict[str, object]:
        if not settings.recovery_enabled:
            return _failure("recovery_disabled")
        if not settings.recovery_observe_only:
            return _failure("observe_only_required")
        if settings.operating_mode is OperatingMode.FREEZE:
            return _failure("freeze_mode")

        active = self._has_active_incident()
        if active is None:
            return _failure("drill_failed")
        if active:
            return _failure("active_incident_present")

        now = self._now()
        healthy, code = self._fresh_healthy_snapshot(now)
        if not healthy:
            return _failure(code or "drill_failed")

        inserted = self._insert_incident(
            now=now,
            threshold=settings.recovery_failure_threshold,
        )
        if isinstance(inserted, dict):
            return inserted
        incident = inserted

        try:
            snapshot = RecoveryStatusService(self.session_factory).record_successful_cycle(
                target=_TARGET,
                observed_at=now,
                summary=_UNHEALTHY_SUMMARY,
            )
        except Exception:
            return _failure("drill_failed")

        if (
            snapshot.get("last_result") != "unhealthy"
            or snapshot.get("ready") is not False
            or snapshot.get("active_incident_id") != incident.id
            or snapshot.get("active_incident_state") != RecoveryIncidentState.SUSPECT.value
            or snapshot.get("consecutive_failures") != settings.recovery_failure_threshold
            or not self._verify_no_mutation_artifacts(incident.id)
        ):
            return _failure("status_verification_failed")

        return {
            "ok": True,
            "target": _TARGET,
            "component": _COMPONENT,
            "incident_id": incident.id,
            "incident_state": RecoveryIncidentState.SUSPECT.value,
            "consecutive_failures": settings.recovery_failure_threshold,
            "status": "unhealthy",
            "observe_only": True,
        }
