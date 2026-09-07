import logging

import pytest

from ai_hq.config import OperatingMode
from ai_hq.recovery.bootstrap import DripVidRecoveryCycle, RecoveryWorkerCoordinator


class Settings:
    recovery_enabled = True
    recovery_observe_only = True
    recovery_observation_seconds = 30
    operating_mode = OperatingMode.SAFE


class HealthyProbe:
    def probe(self):
        return {
            "reachable": True,
            "status_code": 200,
            "ok": True,
            "database": True,
            "secret": "must-not-be-logged",
        }


class HealthyDiagnostics:
    def service_status(self, component):
        return {"active_state": "active"}

    def recent_logs(self, component, *, lines=100):
        return ["password=must-not-be-logged"]


class Recovery:
    def active_incident(self, component):
        return None


class Observer:
    failure_threshold = 3
    observe_only = False


class SummaryCycle:
    def __init__(self, summary, *, worked=False):
        self.last_summary = summary
        self.worked = worked

    def run_once(self, *, observe_only):
        return self.worked

    def handle_execution_result(self, result):
        return None


class FailingCycle:
    last_summary = None

    def run_once(self, *, observe_only):
        raise RuntimeError("probe failed with token=must-not-be-logged")

    def handle_execution_result(self, result):
        return None


def test_healthy_cycle_exposes_only_bounded_observability_summary():
    cycle = DripVidRecoveryCycle(
        Recovery(),
        Observer(),
        HealthyProbe(),
        HealthyDiagnostics(),
    )

    assert cycle.run_once(observe_only=True) is False
    assert cycle.last_summary == {
        "reachable": True,
        "status_code": 200,
        "ready": True,
        "incident_detected": False,
        "incident_resolved": False,
        "worked": False,
    }


def test_due_cycle_emits_structured_heartbeat_without_sensitive_fields(caplog):
    cycle = SummaryCycle(
        {
            "reachable": True,
            "status_code": 200,
            "ready": True,
            "incident_detected": False,
            "incident_resolved": False,
            "worked": False,
            "secret": "must-not-be-logged",
        }
    )
    coordinator = RecoveryWorkerCoordinator(cycle, clock=lambda: 1000.0)

    with caplog.at_level(logging.INFO, logger="ai_hq.recovery"):
        assert coordinator.run_if_due(Settings()) is False

    text = caplog.text
    assert "recovery_cycle" in text
    assert "observe_only=true" in text
    assert "reachable=true" in text
    assert "status_code=200" in text
    assert "ready=true" in text
    assert "incident_detected=false" in text
    assert "incident_resolved=false" in text
    assert "worked=false" in text
    assert "must-not-be-logged" not in text
    assert "secret" not in text


def test_unhealthy_cycle_heartbeat_reports_that_recovery_work_was_detected(caplog):
    cycle = SummaryCycle(
        {
            "reachable": True,
            "status_code": 503,
            "ready": False,
            "incident_detected": True,
            "incident_resolved": False,
            "worked": True,
        },
        worked=True,
    )
    coordinator = RecoveryWorkerCoordinator(cycle, clock=lambda: 1000.0)

    with caplog.at_level(logging.INFO, logger="ai_hq.recovery"):
        assert coordinator.run_if_due(Settings()) is True

    assert "status_code=503" in caplog.text
    assert "ready=false" in caplog.text
    assert "incident_detected=true" in caplog.text
    assert "worked=true" in caplog.text


def test_cycle_failure_is_logged_without_leaking_exception_text(caplog):
    coordinator = RecoveryWorkerCoordinator(FailingCycle(), clock=lambda: 1000.0)

    with caplog.at_level(logging.ERROR, logger="ai_hq.recovery"):
        with pytest.raises(RuntimeError, match="probe failed"):
            coordinator.run_if_due(Settings())

    assert "recovery_cycle_failed" in caplog.text
    assert "must-not-be-logged" not in caplog.text
    assert "token" not in caplog.text
