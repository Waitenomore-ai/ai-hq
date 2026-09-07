from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from ai_hq.config import OperatingMode, Settings
from ai_hq.db import get_session_factory
from ai_hq.host_helper.client import HostHelperClient
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.service import MissionService
from ai_hq.notifications.service import NotificationService
from ai_hq.operations.transport import HostHelperOperationalTransport
from ai_hq.recovery.models import RecoveryIncidentState
from ai_hq.recovery.observer import RecoveryObserver
from ai_hq.recovery.policy import RECOVERY_COMPONENTS
from ai_hq.recovery.probe import (
    HostHelperDripVidReadinessProbe,
    recovery_diagnostic_targets,
)
from ai_hq.recovery.service import RecoveryService
from ai_hq.recovery.status import RecoveryStatusService
from ai_hq.system_state import ensure_system_state


MonotonicClock = Callable[[], float]
logger = logging.getLogger("ai_hq.recovery")


def _log_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def _log_status_code(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return str(value)
    return "unknown"


class ReadinessProbe(Protocol):
    def probe(self) -> dict[str, Any]: ...


class RecoveryStatusRecorder(Protocol):
    def record_successful_cycle(
        self,
        *,
        target: str,
        observed_at: datetime,
        summary: Mapping[str, Any],
    ) -> dict: ...

    def record_cycle_error(
        self,
        *,
        target: str,
        observed_at: datetime,
    ) -> dict: ...


class RecoveryDiagnosticsReader:
    """Read-only fixed-target diagnostic reader used by recovery observation."""

    def __init__(self, transport: HostHelperOperationalTransport) -> None:
        self.transport = transport
        self.targets = recovery_diagnostic_targets()

    def service_status(self, component: str) -> dict[str, Any]:
        recovery_component = RECOVERY_COMPONENTS.get(component)
        if recovery_component is None:
            raise ValueError(f"unknown recovery component: {component}")
        target = self.targets.require(recovery_component.diagnostic_target)
        return dict(self.transport.service_status(target))

    def recent_logs(self, component: str, *, lines: int = 100) -> list[str]:
        recovery_component = RECOVERY_COMPONENTS.get(component)
        if recovery_component is None:
            raise ValueError(f"unknown recovery component: {component}")
        target = self.targets.require(recovery_component.diagnostic_target)
        result = self.transport.service_logs(target, lines=lines)
        text = result.get("text", "")
        if not isinstance(text, str):
            return []
        return text.splitlines()[:lines]


class DripVidRecoveryCycle:
    """Observe one bounded recovery cycle without executing mutations directly."""

    def __init__(
        self,
        recovery: RecoveryService,
        observer: RecoveryObserver,
        probe: ReadinessProbe,
        diagnostics: RecoveryDiagnosticsReader,
    ) -> None:
        self.recovery = recovery
        self.observer = observer
        self.probe = probe
        self.diagnostics = diagnostics
        self.last_summary: dict[str, bool | int | None] | None = None

    @staticmethod
    def _state(status: Mapping[str, Any] | None) -> str | None:
        if status is None:
            return None
        value = status.get("active_state", status.get("state"))
        return value if isinstance(value, str) else None

    @classmethod
    def _service_down(cls, status: Mapping[str, Any] | None) -> bool:
        return (cls._state(status) or "").casefold() in {"inactive", "failed"}

    @classmethod
    def _service_running(cls, status: Mapping[str, Any] | None) -> bool:
        return (cls._state(status) or "").casefold() in {"active", "running"}

    @staticmethod
    def _storage_critical(readiness: Mapping[str, Any]) -> bool:
        storage = readiness.get("storage")
        if not isinstance(storage, Mapping):
            return False
        return storage.get("available") is False or storage.get("writable") is False

    def _component_failed(
        self,
        component: str,
        *,
        readiness: Mapping[str, Any],
        status: Mapping[str, Any] | None,
    ) -> bool:
        if status is None:
            return False
        if self._service_down(status):
            return True
        if component == "app":
            return readiness.get("ok") is not True
        if component == "database":
            return readiness.get("database") is False
        return False

    def _component_healthy(
        self,
        component: str,
        *,
        readiness: Mapping[str, Any],
        status: Mapping[str, Any] | None,
    ) -> bool:
        if status is None or not self._service_running(status):
            return False
        if component == "app":
            return readiness.get("ok") is True
        if component == "database":
            return readiness.get("database") is True
        return True

    def _status_snapshot(self) -> dict[str, dict[str, Any] | None]:
        statuses: dict[str, dict[str, Any] | None] = {}
        for component in RECOVERY_COMPONENTS:
            try:
                statuses[component] = self.diagnostics.service_status(component)
            except Exception:
                statuses[component] = None
        return statuses

    def _record_summary(
        self,
        readiness: Mapping[str, Any],
        *,
        incident_detected: bool,
        incident_resolved: bool,
        worked: bool,
    ) -> None:
        status_code = readiness.get("status_code")
        self.last_summary = {
            "reachable": readiness.get("reachable") if isinstance(readiness.get("reachable"), bool) else None,
            "status_code": (
                status_code
                if isinstance(status_code, int)
                and not isinstance(status_code, bool)
                and 100 <= status_code <= 599
                else None
            ),
            "ready": readiness.get("ok") if isinstance(readiness.get("ok"), bool) else None,
            "incident_detected": incident_detected,
            "incident_resolved": incident_resolved,
            "worked": worked,
        }

    def run_once(self, *, observe_only: bool) -> bool:
        readiness = self.probe.probe()
        statuses = self._status_snapshot()
        previous_observe_only = self.observer.observe_only
        self.observer.observe_only = observe_only
        worked = False
        incident_detected = False
        incident_resolved = False

        try:
            if self._storage_critical(readiness):
                incident = self.recovery.observe_failure(
                    "app",
                    diagnostics={"readiness": readiness},
                )
                incident_detected = True
                worked = True
                if incident.consecutive_failures >= self.observer.failure_threshold:
                    self.observer.handle_policy_escalation(
                        incident.id,
                        readiness=readiness,
                        service_state=self._state(statuses.get("app")),
                    )
                self._record_summary(
                    readiness,
                    incident_detected=incident_detected,
                    incident_resolved=incident_resolved,
                    worked=worked,
                )
                return True

            for component in RECOVERY_COMPONENTS:
                status = statuses.get(component)
                incident = self.recovery.active_incident(component)

                if (
                    incident is not None
                    and incident.state is RecoveryIncidentState.VERIFYING
                    and status is not None
                ):
                    incident_resolved = self.observer.verify_recovery(
                        incident.id,
                        readiness=readiness,
                        service_state=self._state(status),
                    ) or incident_resolved
                    worked = True
                    continue

                if self._component_healthy(
                    component,
                    readiness=readiness,
                    status=status,
                ):
                    if incident is not None:
                        self.recovery.resolve_if_healthy(
                            component,
                            verification={
                                "readiness": readiness,
                                "service_state": self._state(status),
                            },
                        )
                        incident_resolved = True
                        worked = True
                    continue

                if not self._component_failed(
                    component,
                    readiness=readiness,
                    status=status,
                ):
                    continue

                incident = self.recovery.observe_failure(
                    component,
                    diagnostics={"readiness": readiness},
                )
                incident_detected = True
                worked = True

                if incident.consecutive_failures < self.observer.failure_threshold:
                    continue

                try:
                    logs = self.diagnostics.recent_logs(component, lines=100)
                except Exception:
                    logs = []

                self.observer.capture_diagnostics(
                    incident.id,
                    readiness=readiness,
                    service_status=status or {},
                    logs=logs,
                )

                if self.observer.handle_policy_escalation(
                    incident.id,
                    readiness=readiness,
                    service_state=self._state(status),
                ):
                    continue

                self.observer.create_recovery_mission(
                    incident.id,
                    readiness=readiness,
                    service_state=self._state(status),
                )

            self._record_summary(
                readiness,
                incident_detected=incident_detected,
                incident_resolved=incident_resolved,
                worked=worked,
            )
            return worked
        finally:
            self.observer.observe_only = previous_observe_only

    def handle_execution_result(self, result) -> None:
        outcome = getattr(result, "outcome", None)
        mission_id = getattr(result, "mission_id", None)
        if outcome is None or not mission_id:
            return

        incident = self.recovery.incident_for_mission(mission_id)
        if incident is None:
            return

        self.observer.record_mission_outcome(
            incident.id,
            mission_id=mission_id,
            state=outcome.state,
            result=outcome.result,
            reason=outcome.reason,
        )


class RecoveryWorkerCoordinator:
    """Interval gate around the read-only observation cycle."""

    def __init__(
        self,
        cycle: DripVidRecoveryCycle,
        *,
        clock: MonotonicClock = time.monotonic,
        status_recorder: RecoveryStatusRecorder | None = None,
    ) -> None:
        self.cycle = cycle
        self.clock = clock
        self.status_recorder = status_recorder
        self._last_run: float | None = None

    def _record_cycle_error(self, observed_at: datetime) -> None:
        if self.status_recorder is None:
            return
        try:
            self.status_recorder.record_cycle_error(
                target="dripvid",
                observed_at=observed_at,
            )
        except Exception:
            logger.error("recovery_status_persist_failed phase=error")

    def _record_cycle_success(
        self,
        observed_at: datetime,
        summary: Mapping[str, Any],
    ) -> None:
        if self.status_recorder is None:
            return
        try:
            self.status_recorder.record_successful_cycle(
                target="dripvid",
                observed_at=observed_at,
                summary=summary,
            )
        except Exception:
            logger.error("recovery_status_persist_failed phase=success")

    def run_if_due(self, settings: Settings) -> bool:
        if not getattr(settings, "recovery_enabled", False):
            return False
        if settings.operating_mode is OperatingMode.FREEZE:
            return False

        now = float(self.clock())
        if (
            self._last_run is not None
            and now - self._last_run < settings.recovery_observation_seconds
        ):
            return False

        self._last_run = now
        observed_at = datetime.now(UTC)
        try:
            worked = bool(
                self.cycle.run_once(
                    observe_only=settings.recovery_observe_only,
                )
            )
        except Exception:
            logger.error(
                "recovery_cycle_failed timestamp=%s observe_only=%s",
                observed_at.isoformat(),
                _log_bool(settings.recovery_observe_only),
            )
            self._record_cycle_error(observed_at)
            raise

        summary = getattr(self.cycle, "last_summary", None)
        if not isinstance(summary, Mapping):
            summary = {}
        logger.info(
            "recovery_cycle timestamp=%s observe_only=%s reachable=%s status_code=%s "
            "ready=%s incident_detected=%s incident_resolved=%s worked=%s",
            observed_at.isoformat(),
            _log_bool(settings.recovery_observe_only),
            _log_bool(summary.get("reachable")),
            _log_status_code(summary.get("status_code")),
            _log_bool(summary.get("ready")),
            _log_bool(summary.get("incident_detected")),
            _log_bool(summary.get("incident_resolved")),
            _log_bool(worked),
        )
        self._record_cycle_success(observed_at, summary)
        return worked

    def handle_execution_result(self, result) -> None:
        self.cycle.handle_execution_result(result)


def build_recovery_coordinator(
    settings: Settings,
    *,
    session_factory=None,
    clock: MonotonicClock = time.monotonic,
) -> RecoveryWorkerCoordinator | None:
    if not getattr(settings, "recovery_enabled", False):
        return None
    if not getattr(settings, "host_helper_credential", None):
        return None

    if session_factory is None:
        session_factory = get_session_factory()

    ensure_system_state(session_factory)
    ledger = OperationsLedger(session_factory)
    missions = MissionService(session_factory, ledger)
    notifications = NotificationService(session_factory)
    recovery = RecoveryService(
        session_factory,
        failure_threshold=settings.recovery_failure_threshold,
        observation_seconds=settings.recovery_observation_seconds,
        cooldown_seconds=settings.recovery_cooldown_seconds,
        attempt_budget=settings.recovery_attempt_budget,
        budget_window_seconds=settings.recovery_budget_window_seconds,
    )
    helper = HostHelperClient(
        settings.host_helper_socket,
        settings.host_helper_credential,
    )
    transport = HostHelperOperationalTransport(helper)
    diagnostics = RecoveryDiagnosticsReader(transport)
    observer = RecoveryObserver(
        recovery,
        missions,
        failure_threshold=settings.recovery_failure_threshold,
        observe_only=settings.recovery_observe_only,
        notifications=notifications,
    )
    probe = HostHelperDripVidReadinessProbe(helper)
    cycle = DripVidRecoveryCycle(
        recovery,
        observer,
        probe,
        diagnostics,
    )
    status = RecoveryStatusService(session_factory)
    return RecoveryWorkerCoordinator(
        cycle,
        clock=clock,
        status_recorder=status,
    )
