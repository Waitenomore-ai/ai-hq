from types import SimpleNamespace

from ai_hq.notifications.models import NotificationSeverity
from ai_hq.recovery.models import RecoveryIncidentState
from ai_hq.recovery.observer import RecoveryObserver
from ai_hq.tool_gateway.contracts import ToolOutcomeState


HEALTHY_STORAGE = {
    "available": True,
    "writable": True,
    "belowReserve": False,
    "freeBytes": 200,
    "reserveBytes": 50,
}


class RecordingRecovery:
    def __init__(self, *, component="app"):
        self.incident = SimpleNamespace(
            id="incident-1",
            target="dripvid",
            component=component,
            state=RecoveryIncidentState.RECOVERING,
            consecutive_failures=3,
            recovery_mission_id="mission-1",
        )
        self.diagnostics = []
        self.attempts = []
        self.verifying = []
        self.resolved = []
        self.escalated = []

    def get_incident(self, incident_id):
        assert incident_id == self.incident.id
        return self.incident

    def update_diagnostics(self, incident_id, diagnostics):
        self.diagnostics.append((incident_id, diagnostics))
        return self.incident

    def record_attempt(self, incident_id, **kwargs):
        self.attempts.append((incident_id, kwargs))
        return SimpleNamespace(**kwargs)

    def mark_verifying(self, incident_id, *, verification=None):
        self.verifying.append((incident_id, verification or {}))
        self.incident.state = RecoveryIncidentState.VERIFYING
        return self.incident

    def resolve(self, incident_id, *, verification=None):
        self.resolved.append((incident_id, verification or {}))
        self.incident.state = RecoveryIncidentState.RESOLVED
        return self.incident

    def escalate(self, incident_id, *, reason, diagnostics=None):
        self.escalated.append((incident_id, reason, diagnostics or {}))
        self.incident.state = RecoveryIncidentState.ESCALATED
        return self.incident


class NoopMissions:
    pass


class RecordingNotifications:
    def __init__(self):
        self.items = []

    def notify(self, **kwargs):
        self.items.append(kwargs)
        return SimpleNamespace(**kwargs)


def build(*, component="app"):
    recovery = RecordingRecovery(component=component)
    notifications = RecordingNotifications()
    observer = RecoveryObserver(
        recovery,
        NoopMissions(),
        notifications=notifications,
    )
    return observer, recovery, notifications


def test_diagnostics_are_bounded_and_secret_like_log_lines_are_redacted():
    observer, recovery, _notifications = build()
    raw_logs = [f"normal line {index}" for index in range(150)]
    raw_logs.insert(2, "password=do-not-store")
    raw_logs.insert(3, "Authorization: bearer secret")

    observer.capture_diagnostics(
        "incident-1",
        readiness={
            "ok": False,
            "database": True,
            "storage": HEALTHY_STORAGE,
            "ignored": "not persisted",
        },
        service_status={"state": "failed", "unit": "dripvid.service"},
        logs=raw_logs,
    )

    stored = recovery.diagnostics[0][1]
    assert set(stored) == {"readiness", "service_status", "recent_logs"}
    assert len(stored["recent_logs"]) <= 100
    serialized = repr(stored).casefold()
    assert "do-not-store" not in serialized
    assert "bearer secret" not in serialized
    assert "ignored" not in serialized


def test_executed_recovery_records_real_attempt_and_enters_verifying():
    observer, recovery, _notifications = build()

    observer.record_mission_outcome(
        "incident-1",
        mission_id="mission-1",
        state=ToolOutcomeState.EXECUTED,
        result={"active_state": "active"},
    )

    assert recovery.attempts[0][1]["simulated"] is False
    assert recovery.attempts[0][1]["outcome"] == "executed"
    assert recovery.verifying == [
        (
            "incident-1",
            {"mission_state": "executed"},
        )
    ]


def test_simulated_recovery_records_simulated_attempt_and_enters_verifying():
    observer, recovery, _notifications = build()

    observer.record_mission_outcome(
        "incident-1",
        mission_id="mission-1",
        state=ToolOutcomeState.SIMULATED,
        result={"simulated": True},
    )

    assert recovery.attempts[0][1]["simulated"] is True
    assert recovery.attempts[0][1]["outcome"] == "simulated"
    assert len(recovery.verifying) == 1


def test_successful_verification_resolves_and_notifies_information():
    observer, recovery, notifications = build(component="app")

    result = observer.verify_recovery(
        "incident-1",
        readiness={"ok": True, "storage": HEALTHY_STORAGE},
        service_state="active",
    )

    assert result is True
    assert len(recovery.resolved) == 1
    notification = notifications.items[-1]
    assert notification["severity"] is NotificationSeverity.INFORMATION
    assert notification["group_key"] == "recovery:dripvid:app"
    assert notification["source_id"] == "incident-1"


def test_failed_verification_escalates_and_notifies_critical_without_raw_logs():
    observer, recovery, notifications = build(component="app")
    observer.capture_diagnostics(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_status={"state": "failed"},
        logs=["password=never-notify"],
    )

    result = observer.verify_recovery(
        "incident-1",
        readiness={"ok": False, "storage": HEALTHY_STORAGE},
        service_state="failed",
    )

    assert result is False
    assert recovery.escalated[-1][1] == "verification_failed"
    notification = notifications.items[-1]
    assert notification["severity"] is NotificationSeverity.CRITICAL
    assert notification["group_key"] == "recovery:dripvid:app"
    assert "never-notify" not in notification["message"]


def test_storage_unavailable_escalates_with_stable_storage_group_key():
    observer, recovery, notifications = build(component="app")

    handled = observer.handle_policy_escalation(
        "incident-1",
        readiness={
            "ok": False,
            "storage": {**HEALTHY_STORAGE, "available": False},
        },
        service_state="failed",
    )

    assert handled is True
    assert recovery.escalated[-1][1] == "storage_unavailable"
    assert notifications.items[-1]["severity"] is NotificationSeverity.CRITICAL
    assert notifications.items[-1]["group_key"] == "recovery:dripvid:storage"


def test_running_unhealthy_database_escalates_without_restart_notification():
    observer, recovery, notifications = build(component="database")

    handled = observer.handle_policy_escalation(
        "incident-1",
        readiness={
            "ok": False,
            "database": False,
            "storage": HEALTHY_STORAGE,
        },
        service_state="running",
    )

    assert handled is True
    assert recovery.escalated[-1][1] == "database_running_but_unhealthy"
    assert notifications.items[-1]["group_key"] == "recovery:dripvid:database"


def test_blocked_or_waiting_authorization_escalates_without_counting_attempt():
    for state in (ToolOutcomeState.BLOCKED, ToolOutcomeState.WAITING_APPROVAL):
        observer, recovery, notifications = build()

        observer.record_mission_outcome(
            "incident-1",
            mission_id="mission-1",
            state=state,
            reason="required recovery authorization is not available",
        )

        assert recovery.attempts == []
        assert recovery.escalated[-1][1] == "authorization_missing"
        assert notifications.items[-1]["severity"] is NotificationSeverity.CRITICAL
        assert notifications.items[-1]["group_key"] == "recovery:dripvid:app"


def test_failed_real_attempt_counts_and_escalates():
    observer, recovery, notifications = build()

    observer.record_mission_outcome(
        "incident-1",
        mission_id="mission-1",
        state=ToolOutcomeState.FAILED,
        result={"error": "service did not recover"},
    )

    assert recovery.attempts[-1][1]["simulated"] is False
    assert recovery.attempts[-1][1]["outcome"] == "failed"
    assert recovery.escalated[-1][1] == "recovery_attempt_failed"
    assert notifications.items[-1]["severity"] is NotificationSeverity.CRITICAL
