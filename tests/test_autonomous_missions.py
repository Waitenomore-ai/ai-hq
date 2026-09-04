from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent
from ai_hq.db import Base
from ai_hq.missions.executor import MissionExecutor
from ai_hq.missions.models import (
    MissionRisk,
    MissionStatus,
    MissionStepStatus,
)
from ai_hq.missions.service import MissionService
from ai_hq.tool_gateway.contracts import ToolOutcome, ToolOutcomeState
from ai_hq.tool_gateway.registry import ToolRegistry


class FakeAdapter:
    capability = "host.health"

    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return {"healthy": True}


class FakeGateway:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return self.outcomes.pop(0)


def build_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return MissionService(factory), factory


def create_mission(service):
    return service.create_mission(
        title="Autonomous health inspection",
        description="Execute ordered health checks.",
        owner_agent="sysadmin",
        source="direct_user_request",
        priority="normal",
        risk=MissionRisk.GREEN,
    )


def create_plan(service, mission):
    return service.create_plan(
        mission.id,
        [
            {
                "description": "Check AI HQ",
                "tool_name": "host.health",
                "tool_arguments": {
                    "target": "ai-hq",
                    "mutates_external_state": False,
                },
            },
            {
                "description": "Check DripVid",
                "tool_name": "host.health",
                "tool_arguments": {
                    "target": "dripvid",
                    "mutates_external_state": False,
                },
            },
        ],
    )


def test_executor_runs_only_one_pending_step_per_call():
    service, _ = build_service()
    mission = create_mission(service)
    steps = create_plan(service, mission)

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.EXECUTED,
                capability="host.health",
                result={"healthy": True},
            )
        ]
    )

    result = MissionExecutor(service, gateway).run_next(mission.id)

    assert result.mission_status is MissionStatus.RUNNING
    assert result.step_id == steps[0].id
    assert result.step_status is MissionStepStatus.SUCCEEDED
    assert len(gateway.requests) == 1

    persisted = service.list_plan_steps(mission.id)
    assert persisted[0].status is MissionStepStatus.SUCCEEDED
    assert persisted[1].status is MissionStepStatus.PENDING


def test_executor_never_reexecutes_succeeded_step():
    service, _ = build_service()
    mission = create_mission(service)
    steps = create_plan(service, mission)

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.EXECUTED,
                capability="host.health",
                result={"healthy": True},
            ),
            ToolOutcome(
                state=ToolOutcomeState.EXECUTED,
                capability="host.health",
                result={"healthy": True},
            ),
        ]
    )

    executor = MissionExecutor(service, gateway)

    first = executor.run_next(mission.id)
    second = executor.run_next(mission.id)

    assert first.step_id == steps[0].id
    assert second.step_id == steps[1].id
    assert len(gateway.requests) == 2
    assert service.get_mission(mission.id).status is MissionStatus.COMPLETED


def test_gateway_block_fails_step_and_mission_closed():
    service, _ = build_service()
    mission = create_mission(service)
    steps = create_plan(service, mission)

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.BLOCKED,
                capability="host.health",
                reason="permission_denied",
            )
        ]
    )

    result = MissionExecutor(service, gateway).run_next(mission.id)

    assert result.mission_status is MissionStatus.FAILED
    assert result.step_status is MissionStepStatus.FAILED

    step = service.list_plan_steps(mission.id)[0]
    assert step.id == steps[0].id
    assert step.error_state["reason"] == "permission_denied"


def test_gateway_approval_pauses_mission_and_step():
    service, _ = build_service()
    mission = create_mission(service)
    steps = create_plan(service, mission)

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.WAITING_APPROVAL,
                capability="host.health",
                reason="approval_required",
                approval_request_id="approval-123",
            )
        ]
    )

    result = MissionExecutor(service, gateway).run_next(mission.id)

    assert result.mission_status is MissionStatus.WAITING_APPROVAL
    assert result.step_status is MissionStepStatus.WAITING_APPROVAL

    step = service.list_plan_steps(mission.id)[0]
    assert step.id == steps[0].id
    assert step.approval_reference == "approval-123"

    # Calling run_next again must not execute around the approval boundary.
    again = MissionExecutor(service, gateway).run_next(mission.id)
    assert again.mission_status is MissionStatus.WAITING_APPROVAL
    assert again.step_id == steps[0].id
    assert len(gateway.requests) == 1


def test_resume_approved_rechecks_exact_request_through_gateway():
    service, _ = build_service()
    mission = create_mission(service)
    create_plan(service, mission)

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.WAITING_APPROVAL,
                capability="host.health",
                reason="approval_required",
                approval_request_id="approval-123",
            ),
            ToolOutcome(
                state=ToolOutcomeState.EXECUTED,
                capability="host.health",
                result={"healthy": True},
            ),
        ]
    )

    executor = MissionExecutor(service, gateway)
    executor.run_next(mission.id)
    result = executor.resume_approved(mission.id)

    assert result.step_status is MissionStepStatus.SUCCEEDED
    assert len(gateway.requests) == 2

    first = gateway.requests[0]
    second = gateway.requests[1]

    assert first.mission_id == second.mission_id
    assert first.agent_key == second.agent_key
    assert first.capability == second.capability
    assert first.target == second.target
    assert first.params == second.params


def test_simulated_gateway_result_counts_as_safe_completed_step():
    service, _ = build_service()
    mission = create_mission(service)

    service.create_plan(
        mission.id,
        [
            {
                "description": "Simulate operation",
                "tool_name": "host.health",
                "tool_arguments": {"target": "ai-hq"},
            }
        ],
    )

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.SIMULATED,
                capability="host.health",
                result={"simulated": True},
            )
        ]
    )

    result = MissionExecutor(service, gateway).run_next(mission.id)

    assert result.mission_status is MissionStatus.COMPLETED
    assert result.step_status is MissionStepStatus.SUCCEEDED
    assert result.outcome.state is ToolOutcomeState.SIMULATED


def test_request_is_derived_from_persisted_mission_and_step():
    service, _ = build_service()
    mission = create_mission(service)

    service.create_plan(
        mission.id,
        [
            {
                "description": "Check service",
                "tool_name": "host.health",
                "tool_arguments": {
                    "target": "ai-hq",
                    "conditions": {"environment": "production"},
                    "mutates_external_state": False,
                    "probe": "readiness",
                },
            }
        ],
    )

    gateway = FakeGateway(
        [
            ToolOutcome(
                state=ToolOutcomeState.EXECUTED,
                capability="host.health",
                result={"healthy": True},
            )
        ]
    )

    MissionExecutor(service, gateway).run_next(mission.id)

    request = gateway.requests[0]

    assert request.mission_id == mission.id
    assert request.agent_key == "sysadmin"
    assert request.capability == "host.health"
    assert request.target == "ai-hq"
    assert request.risk is MissionRisk.GREEN
    assert request.conditions == {"environment": "production"}
    assert request.mutates_external_state is False
    assert request.params == {"probe": "readiness"}


def test_plan_completion_survives_new_service_instance():
    service, factory = build_service()
    mission = create_mission(service)

    step = service.create_plan(
        mission.id,
        [
            {
                "description": "Persistent step",
                "tool_name": "host.health",
                "tool_arguments": {"target": "ai-hq"},
            }
        ],
    )[0]

    service.transition(mission.id, MissionStatus.RUNNING)
    service.transition_step(step.id, MissionStepStatus.RUNNING)
    service.transition_step(
        step.id,
        MissionStepStatus.SUCCEEDED,
        result={"healthy": True},
    )

    restarted = MissionService(factory)

    assert restarted.plan_is_complete(mission.id) is True
    assert restarted.next_pending_step(mission.id) is None


def test_plan_validation_uses_exact_registered_capability():
    service, _ = build_service()
    mission = create_mission(service)

    adapter = FakeAdapter()
    registry = ToolRegistry([adapter])

    steps = service.create_plan(
        mission.id,
        [
            {
                "description": "Health check",
                "tool_name": "host.health",
                "tool_arguments": {"target": "ai-hq"},
            }
        ],
        tool_registry=registry,
    )

    assert len(steps) == 1
    assert steps[0].tool_name == "host.health"
