from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.config import OperatingMode, Settings
from ai_hq.db import Base
from ai_hq.recovery.drill import RecoveryDrillService
from ai_hq.recovery.models import RecoveryAttempt, RecoveryIncident, RecoveryIncidentState
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


def build_settings(**updates):
    settings = Settings(
        database_url="sqlite+pysqlite://",
        redis_url="redis://localhost:6379/0",
        recovery_enabled=True,
        recovery_observe_only=True,
        operating_mode=OperatingMode.SAFE,
        recovery_failure_threshold=3,
    )
    return settings.model_copy(update=updates)


def record_healthy(factory, observed_at):
    return RecoveryStatusService(factory).record_successful_cycle(
        target="dripvid",
        observed_at=observed_at,
        summary={"reachable": True, "status_code": 200, "ready": True},
    )


def add_active_incident(factory, *, component="mcp", observed_at=None):
    observed_at = observed_at or datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    incident = RecoveryIncident(
        active_key=f"dripvid:{component}",
        target="dripvid",
        component=component,
        state=RecoveryIncidentState.SUSPECT,
        consecutive_failures=1,
        first_failure_at=observed_at,
        last_failure_at=observed_at,
        last_observed_at=observed_at,
        diagnostics={},
        verification={},
    )
    with factory() as db:
        db.add(incident)
        db.commit()
        db.refresh(incident)
    return incident


def test_drill_refuses_when_recovery_disabled():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings(recovery_enabled=False)) == {
        "ok": False,
        "code": "recovery_disabled",
    }


def test_drill_refuses_when_observe_only_disabled():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings(recovery_observe_only=False)) == {
        "ok": False,
        "code": "observe_only_required",
    }


def test_drill_refuses_in_freeze_mode():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings(operating_mode=OperatingMode.FREEZE)) == {
        "ok": False,
        "code": "freeze_mode",
    }


def test_drill_requires_healthy_status():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings()) == {
        "ok": False,
        "code": "healthy_status_required",
    }


def test_drill_requires_probe_no_older_than_five_seconds():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now - timedelta(seconds=6))
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings()) == {
        "ok": False,
        "code": "fresh_healthy_probe_required",
    }


def test_drill_rejects_future_probe_timestamp():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now + timedelta(seconds=1))
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings()) == {
        "ok": False,
        "code": "fresh_healthy_probe_required",
    }


def test_drill_refuses_any_existing_active_dripvid_incident():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    add_active_incident(factory, component="mcp", observed_at=now)
    service = RecoveryDrillService(factory, clock=lambda: now)

    assert service.run(settings=build_settings()) == {
        "ok": False,
        "code": "active_incident_present",
    }


def test_drill_injects_fixed_app_incident_at_configured_threshold():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    settings = build_settings(recovery_failure_threshold=4)
    service = RecoveryDrillService(factory, clock=lambda: now)

    result = service.run(settings=settings)

    with factory() as db:
        incident = db.scalar(
            select(RecoveryIncident).where(RecoveryIncident.active_key == "dripvid:app")
        )
        assert incident is not None
        attempt_count = db.scalar(
            select(func.count(RecoveryAttempt.id)).where(
                RecoveryAttempt.incident_id == incident.id
            )
        )

    assert incident.active_key == "dripvid:app"
    assert incident.target == "dripvid"
    assert incident.component == "app"
    assert incident.state is RecoveryIncidentState.SUSPECT
    assert incident.consecutive_failures == 4
    assert incident.diagnostics == {"drill": True}
    assert incident.verification == {}
    assert incident.recovery_mission_id is None
    assert attempt_count == 0
    assert result == {
        "ok": True,
        "target": "dripvid",
        "component": "app",
        "incident_id": incident.id,
        "incident_state": "suspect",
        "consecutive_failures": 4,
        "status": "unhealthy",
        "observe_only": True,
    }


def test_drill_persists_bounded_unhealthy_status():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    service = RecoveryDrillService(factory, clock=lambda: now)

    result = service.run(settings=build_settings())
    snapshot = RecoveryStatusService(factory).snapshot("dripvid")

    assert result["ok"] is True
    assert snapshot["last_result"] == "unhealthy"
    assert snapshot["reachable"] is True
    assert snapshot["status_code"] == 503
    assert snapshot["ready"] is False
    assert snapshot["consecutive_failures"] == 3
    assert snapshot["active_incident_id"] == result["incident_id"]
    assert snapshot["active_incident_state"] == "suspect"
    assert set(result) == {
        "ok",
        "target",
        "component",
        "incident_id",
        "incident_state",
        "consecutive_failures",
        "status",
        "observe_only",
    }
    assert "drill" not in repr(result)


def test_repeated_drill_fails_closed_while_synthetic_incident_is_active():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    record_healthy(factory, now)
    service = RecoveryDrillService(factory, clock=lambda: now)

    first = service.run(settings=build_settings())
    second = service.run(settings=build_settings())

    assert first["ok"] is True
    assert second == {"ok": False, "code": "active_incident_present"}
