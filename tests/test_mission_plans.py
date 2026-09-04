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


def test_create_plan_rejects_unregistered_tool_before_persisting_steps():
    from ai_hq.tool_gateway.registry import ToolRegistry

    service, factory = build_service()
    mission = create_test_mission(service)
    registry = ToolRegistry([])

    try:
        service.create_plan(
            mission.id,
            [
                {
                    "description": "Attempt an unavailable operation",
                    "tool_name": "host.unregistered",
                    "tool_arguments": {"target": "ai-hq"},
                }
            ],
            tool_registry=registry,
        )
    except (KeyError, ValueError) as exc:
        assert "host.unregistered" in str(exc)
    else:
        raise AssertionError("unregistered tool was accepted into mission plan")

    with factory() as db:
        persisted = (
            db.query(MissionStep)
            .filter(MissionStep.mission_id == mission.id)
            .all()
        )

    assert persisted == []


def test_next_pending_step_is_deterministic_and_skips_succeeded_steps():
    service, _ = build_service()
    mission = create_test_mission(service)

    steps = service.create_plan(
        mission.id,
        [
            {
                "description": "First step",
                "tool_name": "host.health",
                "tool_arguments": {"target": "ai-hq"},
            },
            {
                "description": "Second step",
                "tool_name": "host.health",
                "tool_arguments": {"target": "dripvid"},
            },
        ],
    )

    selected = service.next_pending_step(mission.id)
    assert selected is not None
    assert selected.id == steps[0].id
    assert selected.position == 1

    running = service.transition_step(
        selected.id,
        MissionStepStatus.RUNNING,
    )
    assert running.status is MissionStepStatus.RUNNING

    succeeded = service.transition_step(
        selected.id,
        MissionStepStatus.SUCCEEDED,
        result={"status": "ok"},
    )
    assert succeeded.status is MissionStepStatus.SUCCEEDED
    assert succeeded.result == {"status": "ok"}

    selected = service.next_pending_step(mission.id)
    assert selected is not None
    assert selected.id == steps[1].id
    assert selected.position == 2


def test_completed_plan_has_no_next_pending_step():
    service, _ = build_service()
    mission = create_test_mission(service)

    steps = service.create_plan(
        mission.id,
        [
            {
                "description": "Only step",
                "tool_name": "host.health",
                "tool_arguments": {},
            }
        ],
    )

    service.transition_step(
        steps[0].id,
        MissionStepStatus.RUNNING,
    )
    service.transition_step(
        steps[0].id,
        MissionStepStatus.SUCCEEDED,
    )

    assert service.next_pending_step(mission.id) is None


def test_step_lifecycle_rejects_invalid_transition():
    service, _ = build_service()
    mission = create_test_mission(service)

    step = service.create_plan(
        mission.id,
        [
            {
                "description": "Protected step",
                "tool_name": "host.health",
                "tool_arguments": {},
            }
        ],
    )[0]

    try:
        service.transition_step(
            step.id,
            MissionStepStatus.SUCCEEDED,
        )
    except ValueError as exc:
        assert "invalid mission step transition" in str(exc)
    else:
        raise AssertionError("invalid step transition was accepted")
