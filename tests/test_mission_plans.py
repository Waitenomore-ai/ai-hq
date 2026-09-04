from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.missions.models import (
    MissionRisk,
    MissionStep,
    MissionStepStatus,
)
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


def create_test_mission(service):
    return service.create_mission(
        title="Inspect AI HQ",
        description="Inspect service state using an approved registered tool.",
        owner_agent="sysadmin",
        source="direct_user_request",
        priority="normal",
        risk=MissionRisk.GREEN,
        objectives=["inspect health"],
        dependencies=[],
    )


def test_create_plan_persists_ordered_pending_steps():
    service, factory = build_service()
    mission = create_test_mission(service)

    steps = service.create_plan(
        mission.id,
        [
            {
                "description": "Read AI HQ readiness",
                "tool_name": "system.health.read",
                "tool_arguments": {"service": "ai-hq"},
            },
            {
                "description": "Read DripVid readiness",
                "tool_name": "system.health.read",
                "tool_arguments": {"service": "dripvid"},
            },
        ],
    )

    assert [step.position for step in steps] == [1, 2]
    assert [step.status for step in steps] == [
        MissionStepStatus.PENDING,
        MissionStepStatus.PENDING,
    ]
    assert steps[0].mission_id == mission.id
    assert steps[0].description == "Read AI HQ readiness"
    assert steps[0].tool_name == "system.health.read"
    assert steps[0].tool_arguments == {"service": "ai-hq"}

    with factory() as db:
        persisted = (
            db.query(MissionStep)
            .filter(MissionStep.mission_id == mission.id)
            .order_by(MissionStep.position)
            .all()
        )

    assert len(persisted) == 2
    assert [step.id for step in persisted] == [step.id for step in steps]


def test_create_plan_rejects_empty_plan():
    service, _ = build_service()
    mission = create_test_mission(service)

    try:
        service.create_plan(mission.id, [])
    except ValueError as exc:
        assert "at least one step" in str(exc)
    else:
        raise AssertionError("empty mission plan was accepted")


def test_create_plan_cannot_replace_existing_plan():
    service, _ = build_service()
    mission = create_test_mission(service)

    service.create_plan(
        mission.id,
        [
            {
                "description": "Read readiness",
                "tool_name": "system.health.read",
                "tool_arguments": {},
            }
        ],
    )

    try:
        service.create_plan(
            mission.id,
            [
                {
                    "description": "Run again",
                    "tool_name": "system.health.read",
                    "tool_arguments": {},
                }
            ],
        )
    except ValueError as exc:
        assert "already has a plan" in str(exc)
    else:
        raise AssertionError("existing mission plan was replaced")
