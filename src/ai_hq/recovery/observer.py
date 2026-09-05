from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from ai_hq.missions.models import MissionRisk
from ai_hq.notifications.models import NotificationSeverity
from ai_hq.recovery.policy import decide_recovery
from ai_hq.tool_gateway.contracts import ToolOutcomeState


_SECRET_LINE = re.compile(
    r"(?i)(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"session[_-]?secret|client[_-]?secret|authorization)\s*[:=]"
)

_READINESS_KEYS = frozenset(
    {
        "reachable",
        "status_code",
        "ok",
        "database",
        "jellyfin",
        "radarr",
        "sonarr",
        "qbittorrent",
        "requestSync",
        "storage",
        "error",
    }
)

_STORAGE_KEYS = frozenset(
    {
        "available",
        "writable",
        "belowReserve",
        "freeBytes",
        "reserveBytes",
    }
)

_STATUS_KEYS = frozenset(
    {
        "state",
        "active_state",
        "sub_state",
        "unit",
        "load_state",
    }
)


class RecoveryCoordinator(Protocol):
    def get_incident(self, incident_id: str): ...

    def mark_recovery_pending(self, incident_id: str): ...

    def can_recover(self, incident_id: str): ...

    def attach_mission(self, incident_id: str, mission_id: str): ...

    def update_diagnostics(self, incident_id: str, diagnostics: Mapping[str, Any]): ...

    def record_attempt(self, incident_id: str, **kwargs): ...

    def mark_verifying(self, incident_id: str, *, verification=None): ...

    def resolve(self, incident_id: str, *, verification=None): ...

    def escalate(self, incident_id: str, *, reason: str, diagnostics=None): ...


class RecoveryMissionService(Protocol):
    def create_mission(self, **kwargs): ...

    def create_plan(self, mission_id: str, steps: list[dict]): ...


class RecoveryNotifications(Protocol):
    def notify(self, **kwargs): ...


def _bounded_readiness(readiness: Mapping[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in _READINESS_KEYS:
        if key not in readiness:
            continue
        value = readiness[key]
        if key == "storage":
            if isinstance(value, Mapping):
                bounded[key] = {
                    storage_key: value[storage_key]
                    for storage_key in _STORAGE_KEYS
                    if storage_key in value
                    and isinstance(value[storage_key], (bool, int))
                }
            continue
        if value is None or isinstance(value, (bool, int, str)):
            bounded[key] = value[:128] if isinstance(value, str) else value
    return bounded


def _bounded_service_status(status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (value[:128] if isinstance(value, str) else value)
        for key, value in status.items()
        if key in _STATUS_KEYS
        and (value is None or isinstance(value, (bool, int, str)))
    }


def _bounded_logs(logs: Sequence[str] | str) -> list[str]:
    if isinstance(logs, str):
        lines = logs.splitlines()
    else:
        lines = list(logs)

    bounded: list[str] = []
    for raw in lines[:100]:
        line = str(raw)[:512]
        bounded.append("[redacted]" if _SECRET_LINE.search(line) else line)
    return bounded


def _verification_healthy(component: str, readiness: Mapping[str, Any], service_state: str | None) -> bool:
    state = (service_state or "").casefold()
    service_healthy = state in {"active", "running"}
    if not service_healthy or readiness.get("ok") is not True:
        return False
    if component == "database":
        return readiness.get("database") is True
    return True


class RecoveryObserver:
    """Coordinates recovery through persisted missions and bounded evidence."""

    def __init__(
        self,
        recovery: RecoveryCoordinator,
        missions: RecoveryMissionService,
        *,
        failure_threshold: int = 3,
        observe_only: bool = False,
        notifications: RecoveryNotifications | None = None,
    ) -> None:
        if failure_threshold < 2:
            raise ValueError("failure threshold must be at least 2")

        self.recovery = recovery
        self.missions = missions
        self.failure_threshold = failure_threshold
        self.observe_only = observe_only
        self.notifications = notifications

    def _notify(
        self,
        *,
        severity: NotificationSeverity,
        incident_id: str,
        component: str,
        title: str,
        message: str,
        group_component: str | None = None,
    ) -> None:
        if self.notifications is None:
            return
        self.notifications.notify(
            severity=severity,
            title=title,
            message=message,
            group_key=f"recovery:dripvid:{group_component or component}",
            source_type="recovery_incident",
            source_id=incident_id,
        )

    def capture_diagnostics(
        self,
        incident_id: str,
        *,
        readiness: Mapping[str, Any],
        service_status: Mapping[str, Any],
        logs: Sequence[str] | str,
    ):
        diagnostics = {
            "readiness": _bounded_readiness(readiness),
            "service_status": _bounded_service_status(service_status),
            "recent_logs": _bounded_logs(logs),
        }
        return self.recovery.update_diagnostics(incident_id, diagnostics)

    def create_recovery_mission(
        self,
        incident_id: str,
        *,
        readiness: Mapping[str, Any],
        service_state: str | None,
    ):
        incident = self.recovery.get_incident(incident_id)

        if incident.recovery_mission_id:
            return None

        decision = decide_recovery(
            component=incident.component,
            service_state=service_state,
            consecutive_failures=incident.consecutive_failures,
            failure_threshold=self.failure_threshold,
            readiness=readiness,
        )

        if decision.action != "recover" or self.observe_only:
            return None

        self.recovery.mark_recovery_pending(incident.id)
        allowance = self.recovery.can_recover(incident.id)
        if not allowance.allowed:
            if allowance.reason == "budget_exhausted" and self.notifications is not None:
                self.recovery.escalate(incident.id, reason="budget_exhausted")
                self._notify(
                    severity=NotificationSeverity.CRITICAL,
                    incident_id=incident.id,
                    component=incident.component,
                    title="DripVid recovery budget exhausted",
                    message="Automatic recovery stopped because the component reached its recovery attempt limit.",
                )
            return None

        component = decision.component
        if component is None:
            return None

        mission = self.missions.create_mission(
            title=f"Recover DripVid {component}",
            description=(
                f"Automatically recover the DripVid {component} component "
                "after persistent health failure."
            ),
            owner_agent="sysadmin",
            source="automatic-recovery",
            risk=MissionRisk.BLUE,
            objectives=[
                f"Restore the DripVid {component} component",
                "Verify recovery through the normal guarded execution path",
            ],
        )

        self.missions.create_plan(
            mission.id,
            [
                {
                    "description": f"Recover DripVid {component} service",
                    "tool_name": "service.recover",
                    "tool_arguments": {
                        "target": "dripvid",
                        "component": component,
                        "conditions": {
                            "policy": "dripvid-2.90",
                            "component": component,
                        },
                        "mutates_external_state": True,
                    },
                }
            ],
        )

        self.recovery.attach_mission(incident.id, mission.id)
        return mission

    def handle_policy_escalation(
        self,
        incident_id: str,
        *,
        readiness: Mapping[str, Any],
        service_state: str | None,
    ) -> bool:
        incident = self.recovery.get_incident(incident_id)
        decision = decide_recovery(
            component=incident.component,
            service_state=service_state,
            consecutive_failures=incident.consecutive_failures,
            failure_threshold=self.failure_threshold,
            readiness=readiness,
        )
        if decision.action != "escalate":
            return False

        self.recovery.escalate(
            incident.id,
            reason=decision.reason,
            diagnostics={"readiness": _bounded_readiness(readiness)},
        )
        group_component = (
            "storage"
            if decision.reason in {"storage_unavailable", "storage_unwritable"}
            else "database"
            if decision.reason == "database_running_but_unhealthy"
            else incident.component
        )
        self._notify(
            severity=NotificationSeverity.CRITICAL,
            incident_id=incident.id,
            component=incident.component,
            group_component=group_component,
            title="DripVid recovery requires attention",
            message="Automatic recovery stopped because the incident requires operator attention.",
        )
        return True

    def record_mission_outcome(
        self,
        incident_id: str,
        *,
        mission_id: str,
        state: ToolOutcomeState | str,
        result: Mapping[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        del reason
        outcome_state = ToolOutcomeState(state)
        incident = self.recovery.get_incident(incident_id)

        if outcome_state in {ToolOutcomeState.BLOCKED, ToolOutcomeState.WAITING_APPROVAL}:
            self.recovery.escalate(incident.id, reason="authorization_missing")
            self._notify(
                severity=NotificationSeverity.CRITICAL,
                incident_id=incident.id,
                component=incident.component,
                title="DripVid automatic recovery authorization missing",
                message="Automatic recovery could not proceed through the required authorization boundary.",
            )
            return

        if outcome_state is ToolOutcomeState.SIMULATED:
            self.recovery.record_attempt(
                incident.id,
                mission_id=mission_id,
                simulated=True,
                outcome="simulated",
                result=result or {},
            )
            self.recovery.mark_verifying(
                incident.id,
                verification={"mission_state": "simulated"},
            )
            return

        if outcome_state is ToolOutcomeState.EXECUTED:
            self.recovery.record_attempt(
                incident.id,
                mission_id=mission_id,
                simulated=False,
                outcome="executed",
                result=result or {},
            )
            self.recovery.mark_verifying(
                incident.id,
                verification={"mission_state": "executed"},
            )
            return

        self.recovery.record_attempt(
            incident.id,
            mission_id=mission_id,
            simulated=False,
            outcome="failed",
            result=result or {},
        )
        self.recovery.escalate(incident.id, reason="recovery_attempt_failed")
        self._notify(
            severity=NotificationSeverity.CRITICAL,
            incident_id=incident.id,
            component=incident.component,
            title="DripVid automatic recovery failed",
            message="The bounded recovery attempt did not complete successfully and requires attention.",
        )

    def verify_recovery(
        self,
        incident_id: str,
        *,
        readiness: Mapping[str, Any],
        service_state: str | None,
    ) -> bool:
        incident = self.recovery.get_incident(incident_id)
        verification = {
            "readiness": _bounded_readiness(readiness),
            "service_state": (service_state or "")[:64],
        }

        if _verification_healthy(incident.component, readiness, service_state):
            self.recovery.resolve(incident.id, verification=verification)
            self._notify(
                severity=NotificationSeverity.INFORMATION,
                incident_id=incident.id,
                component=incident.component,
                title="DripVid automatic recovery succeeded",
                message="The component returned to a healthy state after bounded automatic recovery.",
            )
            return True

        self.recovery.escalate(
            incident.id,
            reason="verification_failed",
            diagnostics=verification,
        )
        self._notify(
            severity=NotificationSeverity.CRITICAL,
            incident_id=incident.id,
            component=incident.component,
            title="DripVid recovery verification failed",
            message="The component did not return to a healthy state after the recovery attempt.",
        )
        return False
