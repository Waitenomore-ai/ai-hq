from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

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
from ai_hq.recovery.probe import DripVidReadinessProbe, recovery_diagnostic_targets
from ai_hq.recovery.service import RecoveryService
from ai_hq.system_state import ensure_system_state


MonotonicClock = Callable[[], float]


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
        probe: DripVidReadinessProbe,
        diagnostics: RecoveryDiagnosticsReader,
    ) -> None:
        self.recovery = recovery
        self.observer = observer
        self.probe = probe
        self.diagnostics = diagnostics

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
                # A missing diagnostic is not evidence that a service is down.
                # Fail closed: do not manufacture a recovery-eligible state.
                statuses[component] = None
        return statuses

    def run_once(self, *, observe_only: bool) -> bool:
        readiness = self.probe.probe()
        statuses = self._status_snapshot()
        previous_observe_only = self.observer.observe_only
        self.observer.observe_only = observe_only
        worked = False

        try:
            if self._storage_critical(readiness):
                incident = self.recovery.observe_failure(
                    "app",
                    diagnostics={"readiness": readiness},
                )
                if incident.consecutive_failures >= self.observer.failure_threshold:
                    self.observer.handle_policy_escalation(
                        incident.id,
                        readiness=readiness,
                        service_state=self._state(statuses.get("app")),
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
                    self.observer.verify_recovery(
                        incident.id,
                        readiness=readiness,
                        service_state=self._state(status),
                    )
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
    ) -> None:
        self.cycle = cycle
        self.clock = clock
        self._last_run: float | None = None

    def run_if_due(self, settings: Settings) -> bool:
        if not settings.recovery_enabled:
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
        return bool(
            self.cycle.run_once(
                observe_only=settings.recovery_observe_only,
            )
        )

    def handle_execution_result(self, result) -> None:
        self.cycle.handle_execution_result(result)


def build_recovery_coordinator(
    settings: Settings,
    *,
    session_factory=None,
    clock: MonotonicClock = time.monotonic,
) -> RecoveryWorkerCoordinator | None:
    if not settings.recovery_enabled:
        return None
    if not settings.host_helper_credential:
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
    probe = DripVidReadinessProbe(settings.recovery_dripvid_ready_url)
    cycle = DripVidRecoveryCycle(
        recovery,
        observer,
        probe,
        diagnostics,
    )
    return RecoveryWorkerCoordinator(cycle, clock=clock)
