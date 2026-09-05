from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ai_hq.missions.models import MissionRisk
from ai_hq.recovery.policy import decide_recovery


class RecoveryCoordinator(Protocol):
    def get_incident(self, incident_id: str): ...

    def mark_recovery_pending(self, incident_id: str): ...

    def can_recover(self, incident_id: str): ...

    def attach_mission(self, incident_id: str, mission_id: str): ...


class RecoveryMissionService(Protocol):
    def create_mission(self, **kwargs): ...

    def create_plan(self, mission_id: str, steps: list[dict]): ...


class RecoveryObserver:
    """Coordinates recovery by creating audited missions only.

    The observer has no Tool Gateway, transport, adapter, Host Helper, or
    subprocess dependency. A later normal autonomous-worker iteration executes
    the persisted recovery mission through the existing security boundary.
    """

    def __init__(
        self,
        recovery: RecoveryCoordinator,
        missions: RecoveryMissionService,
        *,
        failure_threshold: int = 3,
        observe_only: bool = False,
    ) -> None:
        if failure_threshold < 2:
            raise ValueError("failure threshold must be at least 2")

        self.recovery = recovery
        self.missions = missions
        self.failure_threshold = failure_threshold
        self.observe_only = observe_only

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
