from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ai_hq.recovery.models import (
    RecoveryAttempt,
    RecoveryIncident,
    RecoveryIncidentState,
)
from ai_hq.recovery.policy import RECOVERY_COMPONENTS


SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]


class RecoveryPersistenceError(RuntimeError):
    """Recovery coordination state could not be persisted safely."""


@dataclass(frozen=True, slots=True)
class RecoveryAllowance:
    allowed: bool
    reason: str
    real_attempts: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return value[:1024]

    if isinstance(value, Mapping):
        bounded: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                break
            bounded[str(key)[:128]] = _bounded_value(item, depth=depth + 1)
        return bounded

    if isinstance(value, (list, tuple)):
        return [
            _bounded_value(item, depth=depth + 1)
            for item in value[:20]
        ]

    return str(value)[:1024]


def _bounded_mapping(value: Mapping[str, Any] | None) -> dict:
    if value is None:
        return {}
    return _bounded_value(value)


class RecoveryService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        clock: Clock | None = None,
        failure_threshold: int = 3,
        observation_seconds: int = 30,
        cooldown_seconds: int = 300,
        attempt_budget: int = 2,
        budget_window_seconds: int = 3600,
    ) -> None:
        if failure_threshold < 2:
            raise ValueError("failure threshold must be at least 2")
        if observation_seconds < 1:
            raise ValueError("observation interval must be positive")
        if cooldown_seconds < 1:
            raise ValueError("recovery cooldown must be positive")
        if attempt_budget < 1:
            raise ValueError("recovery attempt budget must be positive")
        if budget_window_seconds < cooldown_seconds:
            raise ValueError("recovery budget window must cover cooldown")

        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.failure_threshold = failure_threshold
        self.observation_seconds = observation_seconds
        self.cooldown_seconds = cooldown_seconds
        self.attempt_budget = attempt_budget
        self.budget_window_seconds = budget_window_seconds

    def _now(self) -> datetime:
        return _utc(self.clock())

    @staticmethod
    def _active_key(component: str) -> str:
        if component not in RECOVERY_COMPONENTS:
            raise ValueError(f"unknown recovery component: {component}")
        return f"dripvid:{component}"

    def get_incident(self, incident_id: str) -> RecoveryIncident:
        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")
                return incident
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("recovery incident read failed") from exc

    def active_incident(self, component: str) -> RecoveryIncident | None:
        active_key = self._active_key(component)
        try:
            with self.session_factory() as db:
                return db.scalar(
                    select(RecoveryIncident)
                    .where(RecoveryIncident.active_key == active_key)
                    .limit(1)
                )
        except Exception as exc:
            raise RecoveryPersistenceError("active recovery incident read failed") from exc

    def observe_failure(
        self,
        component: str,
        *,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> RecoveryIncident:
        active_key = self._active_key(component)
        now = self._now()
        bounded_diagnostics = _bounded_mapping(diagnostics)

        try:
            with self.session_factory() as db:
                incident = db.scalar(
                    select(RecoveryIncident)
                    .where(RecoveryIncident.active_key == active_key)
                    .limit(1)
                )

                if incident is None:
                    incident = RecoveryIncident(
                        active_key=active_key,
                        target="dripvid",
                        component=component,
                        state=RecoveryIncidentState.SUSPECT,
                        consecutive_failures=1,
                        first_failure_at=now,
                        last_failure_at=now,
                        last_observed_at=now,
                        diagnostics=bounded_diagnostics,
                        verification={},
                    )
                    db.add(incident)
                    db.commit()
                    db.refresh(incident)
                    return incident

                elapsed = now - _utc(incident.last_observed_at)
                if elapsed < timedelta(seconds=self.observation_seconds):
                    return incident

                incident.consecutive_failures += 1
                incident.last_failure_at = now
                incident.last_observed_at = now
                if bounded_diagnostics:
                    incident.diagnostics = bounded_diagnostics

                if (
                    incident.state is RecoveryIncidentState.SUSPECT
                    and incident.consecutive_failures >= self.failure_threshold
                ):
                    incident.state = RecoveryIncidentState.DIAGNOSING

                db.commit()
                db.refresh(incident)
                return incident
        except Exception as exc:
            raise RecoveryPersistenceError("failed to persist recovery failure") from exc

    def resolve_if_healthy(
        self,
        component: str,
        *,
        verification: Mapping[str, Any] | None = None,
    ) -> RecoveryIncident | None:
        active_key = self._active_key(component)
        now = self._now()

        try:
            with self.session_factory() as db:
                incident = db.scalar(
                    select(RecoveryIncident)
                    .where(RecoveryIncident.active_key == active_key)
                    .limit(1)
                )
                if incident is None:
                    return None

                incident.state = RecoveryIncidentState.RESOLVED
                incident.active_key = None
                incident.consecutive_failures = 0
                incident.last_observed_at = now
                incident.resolved_at = now
                incident.verification = _bounded_mapping(verification)
                db.commit()
                db.refresh(incident)
                return incident
        except Exception as exc:
            raise RecoveryPersistenceError("failed to resolve recovery incident") from exc

    def mark_recovery_pending(self, incident_id: str) -> RecoveryIncident:
        now = self._now()
        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")
                if incident.active_key is None:
                    raise ValueError("terminal recovery incident cannot be pending")
                if incident.state not in {
                    RecoveryIncidentState.SUSPECT,
                    RecoveryIncidentState.DIAGNOSING,
                    RecoveryIncidentState.RECOVERY_PENDING,
                }:
                    raise ValueError("recovery incident cannot become pending")

                incident.state = RecoveryIncidentState.RECOVERY_PENDING
                incident.last_observed_at = now
                db.commit()
                db.refresh(incident)
                return incident
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("failed to mark recovery pending") from exc

    def can_recover(self, incident_id: str) -> RecoveryAllowance:
        now = self._now()
        window_start = now - timedelta(seconds=self.budget_window_seconds)

        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")

                if (
                    incident.active_key is None
                    or incident.state is not RecoveryIncidentState.RECOVERY_PENDING
                ):
                    return RecoveryAllowance(False, "state_not_pending", 0)

                real_attempts = db.scalar(
                    select(func.count(RecoveryAttempt.id)).where(
                        RecoveryAttempt.target == incident.target,
                        RecoveryAttempt.component == incident.component,
                        RecoveryAttempt.simulated.is_(False),
                        RecoveryAttempt.attempted_at >= window_start,
                    )
                ) or 0

                if real_attempts >= self.attempt_budget:
                    return RecoveryAllowance(
                        False,
                        "budget_exhausted",
                        int(real_attempts),
                    )

                if incident.last_recovery_attempt_at is not None:
                    elapsed = now - _utc(incident.last_recovery_attempt_at)
                    if elapsed < timedelta(seconds=self.cooldown_seconds):
                        return RecoveryAllowance(
                            False,
                            "cooldown",
                            int(real_attempts),
                        )

                return RecoveryAllowance(True, "allowed", int(real_attempts))
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("failed to evaluate recovery limits") from exc

    def claim_recovery(self, incident_id: str) -> bool:
        now = self._now()

        try:
            with self.session_factory() as db:
                claimed = db.execute(
                    update(RecoveryIncident)
                    .where(
                        RecoveryIncident.id == incident_id,
                        RecoveryIncident.active_key.is_not(None),
                        RecoveryIncident.state
                        == RecoveryIncidentState.RECOVERY_PENDING,
                    )
                    .values(
                        state=RecoveryIncidentState.RECOVERING,
                        updated_at=now,
                    )
                )

                if claimed.rowcount != 1:
                    db.rollback()
                    return False

                db.commit()
                return True
        except Exception as exc:
            raise RecoveryPersistenceError("failed to claim recovery incident") from exc

    def record_attempt(
        self,
        incident_id: str,
        *,
        mission_id: str | None,
        simulated: bool,
        outcome: str,
        result: Mapping[str, Any] | None = None,
    ) -> RecoveryAttempt:
        now = self._now()

        if not outcome or len(outcome) > 32:
            raise ValueError("invalid recovery attempt outcome")

        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")

                attempt = RecoveryAttempt(
                    incident_id=incident.id,
                    target=incident.target,
                    component=incident.component,
                    mission_id=mission_id,
                    attempted_at=now,
                    simulated=simulated,
                    outcome=outcome,
                    result=_bounded_mapping(result),
                )
                db.add(attempt)

                if not simulated:
                    incident.last_recovery_attempt_at = now

                db.commit()
                db.refresh(attempt)
                return attempt
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("failed to record recovery attempt") from exc

    def mark_verifying(
        self,
        incident_id: str,
        *,
        verification: Mapping[str, Any] | None = None,
    ) -> RecoveryIncident:
        return self._set_active_state(
            incident_id,
            RecoveryIncidentState.VERIFYING,
            verification=verification,
        )

    def resolve(
        self,
        incident_id: str,
        *,
        verification: Mapping[str, Any] | None = None,
    ) -> RecoveryIncident:
        now = self._now()
        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")

                incident.state = RecoveryIncidentState.RESOLVED
                incident.active_key = None
                incident.consecutive_failures = 0
                incident.resolved_at = now
                incident.last_observed_at = now
                incident.verification = _bounded_mapping(verification)
                db.commit()
                db.refresh(incident)
                return incident
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("failed to resolve recovery incident") from exc

    def escalate(
        self,
        incident_id: str,
        *,
        reason: str,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> RecoveryIncident:
        if not reason:
            raise ValueError("recovery escalation reason is required")

        now = self._now()
        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")

                incident.state = RecoveryIncidentState.ESCALATED
                incident.active_key = None
                incident.escalation_reason = reason[:2048]
                incident.resolved_at = now
                incident.last_observed_at = now
                if diagnostics is not None:
                    incident.diagnostics = _bounded_mapping(diagnostics)
                db.commit()
                db.refresh(incident)
                return incident
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("failed to escalate recovery incident") from exc

    def _set_active_state(
        self,
        incident_id: str,
        state: RecoveryIncidentState,
        *,
        verification: Mapping[str, Any] | None = None,
    ) -> RecoveryIncident:
        now = self._now()
        try:
            with self.session_factory() as db:
                incident = db.get(RecoveryIncident, incident_id)
                if incident is None:
                    raise KeyError(f"recovery incident not found: {incident_id}")
                if incident.active_key is None:
                    raise ValueError("terminal recovery incident cannot transition")

                incident.state = state
                incident.last_observed_at = now
                if verification is not None:
                    incident.verification = _bounded_mapping(verification)
                db.commit()
                db.refresh(incident)
                return incident
        except (KeyError, ValueError):
            raise
        except Exception as exc:
            raise RecoveryPersistenceError("failed to transition recovery incident") from exc
