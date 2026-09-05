from inspect import signature
from types import SimpleNamespace

from ai_hq.missions.models import MissionRisk
from ai_hq.recovery.models import RecoveryIncidentState
from ai_hq.recovery.observer import RecoveryObserver
from ai_hq.recovery.service import RecoveryAllowance


HEALTHY_STORAGE = {
    "available": True,
    "writable": True,
    "belowReserve": False,
    "freeBytes": 200,
    "reserveBytes": 50,
}


class FakeRecoveryService:
    def __init__(self, incident, *, allowance=None):
        self.incident = incident
        self.allowance = allowance or RecoveryAllowance(True, "allowed", 0)
        self.pending_calls = []
        self.attached = []
        self.escalations = []

    def get_incident(self, incident_id):
        assert incident_id == self.incident.id
        return self.incident

    def mark_recovery_pending(self, incident_id):
        self.pending_calls.append(incident_id)
        self.incident.state = RecoveryIncidentState.RECOVERY_PENDING
        return self.incident

    def can_recover(self, incident_id):
        assert incident_id == self.incident.id
        return self.allowance

    def attach_mission(self, incident_id, mission_id):
        self.attached.append((incident_id, mission_id))
        self.incident.recovery_mission_id = mission_id
        return self.incident


class FakeMissionService:
    def __init__(self):
        self.created = []
        self.plans = []

    def create_mission(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=f"mission-{len(self.created)}", **kwargs)

    def create_plan(self, mission_id, steps):
        self.plans.append((mission_id, steps))
        return steps


def incident(*, component="app", failures=3, mission_id=None):
    return SimpleNamespace(
        id="incident-1",
        target="dripvid",
        component=component,
        state=RecoveryIncidentState.DIAGNOSING,
        consecutive_failures=failures,
        recovery_mission_id=mission_id,
    )


def build_observer(inc, *, allowance=None, observe_only=False):
    recovery = FakeRecoveryService(inc, allowance=allowance)
    missions = FakeMissionService()
    observer = RecoveryObserver(
        recovery,
        missions,
        failure_threshold=3,
        observe_only=observe_only,
    )
    return observer, recovery, missions


def test_eligible_incident_creates_one_blue_sysadmin_recovery_mission():
    observer, recovery, missions = build_observer(incident())

    mission = observer.create_recovery_mission(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_state="failed",
    )

    assert mission.id == "mission-1"
    assert len(missions.created) == 1
    created = missions.created[0]
    assert created["owner_agent"] == "sysadmin"
    assert created["risk"] is MissionRisk.BLUE
    assert created["source"] == "automatic-recovery"

    assert missions.plans == [
        (
            "mission-1",
            [
                {
                    "description": "Recover DripVid app service",
                    "tool_name": "service.recover",
                    "tool_arguments": {
                        "target": "dripvid",
                        "component": "app",
                        "conditions": {
                            "policy": "dripvid-2.90",
                            "component": "app",
                        },
                        "mutates_external_state": True,
                    },
                }
            ],
        )
    ]
    assert recovery.attached == [("incident-1", "mission-1")]


def test_no_mission_below_failure_threshold():
    observer, _recovery, missions = build_observer(incident(failures=2))

    assert observer.create_recovery_mission(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_state="failed",
    ) is None
    assert missions.created == []


def test_storage_incident_never_creates_recovery_mission():
    observer, _recovery, missions = build_observer(incident())

    assert observer.create_recovery_mission(
        "incident-1",
        readiness={
            "ok": False,
            "storage": {**HEALTHY_STORAGE, "available": False},
        },
        service_state="failed",
    ) is None
    assert missions.created == []


def test_running_but_unhealthy_database_never_creates_recovery_mission():
    observer, _recovery, missions = build_observer(incident(component="database"))

    assert observer.create_recovery_mission(
        "incident-1",
        readiness={
            "ok": False,
            "database": False,
            "storage": HEALTHY_STORAGE,
        },
        service_state="active",
    ) is None
    assert missions.created == []


def test_cooldown_or_budget_block_creates_no_mission():
    observer, _recovery, missions = build_observer(
        incident(),
        allowance=RecoveryAllowance(False, "budget_exhausted", 2),
    )

    assert observer.create_recovery_mission(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_state="failed",
    ) is None
    assert missions.created == []


def test_existing_recovery_mission_is_not_duplicated():
    observer, _recovery, missions = build_observer(
        incident(mission_id="existing-mission"),
    )

    assert observer.create_recovery_mission(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_state="failed",
    ) is None
    assert missions.created == []


def test_observe_only_mode_never_creates_mutation_mission():
    observer, _recovery, missions = build_observer(
        incident(),
        observe_only=True,
    )

    assert observer.create_recovery_mission(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_state="failed",
    ) is None
    assert missions.created == []


def test_observer_constructor_has_no_direct_mutation_dependency():
    parameters = set(signature(RecoveryObserver).parameters)

    assert "gateway" not in parameters
    assert "transport" not in parameters
    assert "host_helper" not in parameters
    assert "adapter" not in parameters
