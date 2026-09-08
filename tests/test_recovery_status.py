from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.recovery.models import RecoveryIncident, RecoveryIncidentState
from ai_hq.recovery.status import RecoveryStatusService


def build_factory():
    import ai_hq.missions.models  # noqa: F401

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def active_incident(factory, *, failures=2):
    observed_at = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)
    incident = RecoveryIncident(
        active_key="dripvid:app",
        target="dripvid",
        component="app",
        state=RecoveryIncidentState.SUSPECT,
        consecutive_failures=failures,
        first_failure_at=observed_at,
        last_failure_at=observed_at,
        last_observed_at=observed_at,
        diagnostics={"secret": "must-not-project"},
        verification={"raw": "must-not-project"},
    )
    with factory() as db:
        db.add(incident)
        db.commit()
        db.refresh(incident)
    return incident


def test_successful_cycle_persists_only_bounded_healthy_snapshot():
    factory = build_factory()
    service = RecoveryStatusService(factory)
    observed_at = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)

    result = service.record_successful_cycle(
        target="dripvid",
        observed_at=observed_at,
        summary={
            "reachable": True,
            "status_code": 200,
            "ready": True,
            "secret": "must-not-persist",
            "raw": {"password": "must-not-persist"},
        },
    )

    assert result == service.snapshot("dripvid")
    assert set(result) == {
        "last_probe_at",
        "last_result",
        "reachable",
        "status_code",
        "ready",
        "consecutive_failures",
        "active_incident_id",
        "active_incident_state",
    }
    assert result["last_probe_at"] == observed_at
    assert result["last_result"] == "healthy"
    assert result["reachable"] is True
    assert result["status_code"] == 200
    assert result["ready"] is True
    assert result["consecutive_failures"] == 0
    assert result["active_incident_id"] is None
    assert result["active_incident_state"] is None
    assert "must-not-persist" not in repr(result)


def test_malformed_summary_values_are_rejected_and_unknown():
    factory = build_factory()
    service = RecoveryStatusService(factory)
    observed_at = datetime(2026, 9, 7, 19, 1, tzinfo=UTC)

    result = service.record_successful_cycle(
        target="dripvid",
        observed_at=observed_at,
        summary={"reachable": "yes", "status_code": True, "ready": 1},
    )

    assert result["reachable"] is None
    assert result["status_code"] is None
    assert result["ready"] is None
    assert result["last_result"] == "unknown"


def test_active_incident_projects_only_id_state_and_failure_count():
    factory = build_factory()
    incident = active_incident(factory, failures=2)
    service = RecoveryStatusService(factory)
    observed_at = datetime(2026, 9, 7, 19, 2, tzinfo=UTC)

    result = service.record_successful_cycle(
        target="dripvid",
        observed_at=observed_at,
        summary={"reachable": True, "status_code": 200, "ready": True},
    )

    assert result["last_result"] == "unhealthy"
    assert result["active_incident_id"] == incident.id
    assert result["active_incident_state"] == "suspect"
    assert result["consecutive_failures"] == 2
    assert "must-not-project" not in repr(result)


def test_missing_status_row_returns_stable_unknown_snapshot():
    service = RecoveryStatusService(build_factory())

    assert service.snapshot("dripvid") == {
        "last_probe_at": None,
        "last_result": "unknown",
        "reachable": None,
        "status_code": None,
        "ready": None,
        "consecutive_failures": 0,
        "active_incident_id": None,
        "active_incident_state": None,
    }


def test_cycle_error_clears_probe_fields_without_accepting_exception_text():
    factory = build_factory()
    incident = active_incident(factory, failures=3)
    service = RecoveryStatusService(factory)
    observed_at = datetime(2026, 9, 7, 19, 3, tzinfo=UTC)

    result = service.record_cycle_error(
        target="dripvid",
        observed_at=observed_at,
    )

    assert result["last_probe_at"] == observed_at
    assert result["last_result"] == "error"
    assert result["reachable"] is None
    assert result["status_code"] is None
    assert result["ready"] is None
    assert result["active_incident_id"] == incident.id
    assert result["active_incident_state"] == "suspect"
    assert result["consecutive_failures"] == 3
