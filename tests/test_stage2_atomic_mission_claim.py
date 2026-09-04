from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk, MissionStepStatus
from ai_hq.missions.service import MissionService


def build_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    return MissionService(factory)


def create_two_step_mission(service):
    mission = service.create_mission(
        title="Atomic sequential claim",
        description="Mission steps must execute sequentially.",
        owner_agent="sysadmin",
        source="test",
        priority="normal",
        risk=MissionRisk.GREEN,
    )

    service.create_plan(
        mission.id,
        [
            {
                "description": "first",
                "tool_name": "system.health.read",
                "tool_arguments": {},
            },
            {
                "description": "second",
                "tool_name": "system.health.read",
                "tool_arguments": {},
            },
        ],
    )

    return mission


def test_later_step_cannot_be_claimed_while_first_step_is_running():
    service = build_service()
    mission = create_two_step_mission(service)

    first = service.claim_next_pending_step(mission.id)
    second = service.claim_next_pending_step(mission.id)

    assert first is not None
    assert first.position == 1
    assert first.status is MissionStepStatus.RUNNING

    # A second worker must not skip the RUNNING first step and claim step 2.
    assert second is None


def test_next_step_becomes_claimable_after_first_step_succeeds():
    service = build_service()
    mission = create_two_step_mission(service)

    first = service.claim_next_pending_step(mission.id)

    assert first is not None
    assert first.position == 1

    service.transition_step(
        first.id,
        MissionStepStatus.SUCCEEDED,
        result={"ok": True},
    )

    second = service.claim_next_pending_step(mission.id)

    assert second is not None
    assert second.position == 2
    assert second.status is MissionStepStatus.RUNNING
