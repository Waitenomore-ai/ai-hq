from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.config import OperatingMode, Settings
from ai_hq.db import Base
from ai_hq.recovery.bootstrap import DripVidRecoveryCycle, RecoveryWorkerCoordinator
from ai_hq.recovery.drill import RecoveryDrillService
from ai_hq.recovery.models import RecoveryAttempt, RecoveryIncident, RecoveryIncidentState
from ai_hq.recovery.service import RecoveryService
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


def build_settings():
    return Settings(
        database_url="sqlite+pysqlite://",
        redis_url="redis://localhost:6379/0",
        recovery_enabled=True,
        recovery_observe_only=True,
        operating_mode=OperatingMode.SAFE,
        recovery_failure_threshold=3,
        recovery_observation_seconds=30,
    )


class HealthyProbe:
    def probe(self):
        return {
            "reachable": True,
            "status_code": 200,
            "ok": True,
            "database": True,
            "storage": {"available": True, "writable": True},
        }


class HealthyDiagnostics:
    def service_status(self, component):
        return {"active_state": "active"}

    def recent_logs(self, component, *, lines=100):
        return []


class ObserveOnlyObserver:
    failure_threshold = 3
    observe_only = True


def test_normal_healthy_worker_cycle_resolves_drill_incident_without_mutation():
    now = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    factory = build_factory()
    settings = build_settings()
    status = RecoveryStatusService(factory)
    status.record_successful_cycle(
        target="dripvid",
        observed_at=now,
        summary={"reachable": True, "status_code": 200, "ready": True},
    )

    drill = RecoveryDrillService(factory, clock=lambda: now)
    drill_result = drill.run(settings=settings)
    assert drill_result["ok"] is True

    recovery = RecoveryService(
        factory,
        clock=lambda: now,
        failure_threshold=settings.recovery_failure_threshold,
        observation_seconds=settings.recovery_observation_seconds,
        cooldown_seconds=settings.recovery_cooldown_seconds,
        attempt_budget=settings.recovery_attempt_budget,
        budget_window_seconds=settings.recovery_budget_window_seconds,
    )
    cycle = DripVidRecoveryCycle(
        recovery,
        ObserveOnlyObserver(),
        HealthyProbe(),
        HealthyDiagnostics(),
    )
    coordinator = RecoveryWorkerCoordinator(
        cycle,
        clock=lambda: 1000.0,
        status_recorder=status,
    )

    assert coordinator.run_if_due(settings) is True

    snapshot = status.snapshot("dripvid")
    assert snapshot["last_result"] == "healthy"
    assert snapshot["ready"] is True
    assert snapshot["active_incident_id"] is None
    assert snapshot["active_incident_state"] is None
    assert snapshot["consecutive_failures"] == 0

    with factory() as db:
        incident = db.scalar(
            select(RecoveryIncident).where(
                RecoveryIncident.id == drill_result["incident_id"]
            )
        )
        assert incident is not None
        attempts = db.scalar(
            select(func.count(RecoveryAttempt.id)).where(
                RecoveryAttempt.incident_id == incident.id
            )
        )

    assert incident.state is RecoveryIncidentState.RESOLVED
    assert incident.active_key is None
    assert incident.recovery_mission_id is None
    assert attempts == 0
