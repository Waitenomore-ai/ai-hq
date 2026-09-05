import importlib
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.recovery.service import RecoveryService


def build_service():
    importlib.import_module("ai_hq.missions.models")
    importlib.import_module("ai_hq.recovery.models")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return RecoveryService(
        factory,
        clock=lambda: datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
    )


def test_worker_can_find_active_incident_by_recovery_mission_id():
    service = build_service()
    incident = service.observe_failure("app")
    service.mark_recovery_pending(incident.id)
    service.attach_mission(incident.id, "mission-worker-1")

    found = service.incident_for_mission("mission-worker-1")

    assert found is not None
    assert found.id == incident.id
    assert found.recovery_mission_id == "mission-worker-1"


def test_unknown_recovery_mission_returns_none():
    service = build_service()

    assert service.incident_for_mission("not-a-recovery-mission") is None
