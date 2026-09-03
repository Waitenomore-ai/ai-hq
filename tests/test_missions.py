from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk, MissionStatus
from ai_hq.missions.service import MissionService


def build_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return MissionService(factory), factory


def test_create_mission_defaults_to_queued_and_persists_core_fields():
    service, _ = build_service()
    mission = service.create_mission(
        title="Check AI HQ health",
        description="Inspect current service health without mutating anything.",
        owner_agent="sysadmin",
        source="direct_user_request",
        priority="normal",
        risk=MissionRisk.GREEN,
        objectives=["check readiness", "summarize result"],
        dependencies=[],
    )
    assert mission.status is MissionStatus.QUEUED
    assert mission.owner_agent == "sysadmin"
    assert mission.objectives == ["check readiness", "summarize result"]


def test_valid_transition_sequence_and_terminal_state_protection():
    service, _ = build_service()
    mission = service.create_mission(
        title="Prepare briefing",
        description="Prepare a morning briefing.",
        owner_agent="commander",
        source="scheduled_automation",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    mission = service.transition(mission.id, MissionStatus.RUNNING)
    assert mission.status is MissionStatus.RUNNING
    mission = service.transition(mission.id, MissionStatus.COMPLETED, result={"summary": "done"})
    assert mission.status is MissionStatus.COMPLETED
    assert mission.result == {"summary": "done"}

    try:
        service.transition(mission.id, MissionStatus.RUNNING)
    except ValueError as exc:
        assert "invalid mission transition" in str(exc)
    else:
        raise AssertionError("terminal mission transitioned unexpectedly")


def test_failed_transition_persists_error_state():
    service, _ = build_service()
    mission = service.create_mission(
        title="Collect logs",
        description="Read logs only.",
        owner_agent="sysadmin",
        source="proactive_monitoring",
        priority="high",
        risk=MissionRisk.GREEN,
    )
    failed = service.transition(mission.id, MissionStatus.FAILED, error_state={"code": "probe_failed"})
    assert failed.status is MissionStatus.FAILED
    assert failed.error_state == {"code": "probe_failed"}


def test_running_missions_returns_only_running_in_stable_order():
    service, _ = build_service()
    first = service.create_mission(
        title="first", description="", owner_agent="commander", source="test"
    )
    second = service.create_mission(
        title="second", description="", owner_agent="commander", source="test"
    )
    service.transition(first.id, MissionStatus.RUNNING)

    running = service.running_missions()

    assert [mission.id for mission in running] == [first.id]
    assert service.has_running() is True
    assert second.status is MissionStatus.QUEUED


def test_has_running_is_false_when_no_mission_is_running():
    service, _ = build_service()
    service.create_mission(
        title="queued", description="", owner_agent="commander", source="test"
    )

    assert service.has_running() is False
