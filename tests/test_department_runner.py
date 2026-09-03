from ai_hq.departments.runner import DepartmentRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent, AgentStatus
from ai_hq.agents.registry import AgentRegistry
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.departments.commander import route_sysadmin_mission
from ai_hq.departments.sysadmin import SysAdminService
from ai_hq.host_helper.contracts import HelperResponse, HostAllowLists, HostCapability
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import Mission, MissionRisk, MissionStatus
from ai_hq.missions.service import MissionService
from ai_hq.models.system_state import SystemState
from ai_hq.safety.service import SafetyService

ALLOW_LISTS = HostAllowLists(
    services=frozenset({"ai-hq", "nginx", "dripvid"}),
    containers=frozenset({"ai-hq-web", "ai-hq-worker", "dripvid"}),
    logs=frozenset({"ai-hq", "nginx", "dripvid"}),
)


def build_runtime():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ledger = OperationsLedger(factory)
    missions = MissionService(factory, ledger)
    agents = AgentRegistry(factory)
    agents.ensure_phase1_agents()
    with factory() as db:
        db.add(
            SystemState(
                id=1,
                operating_mode=OperatingMode.NORMAL.value,
                simulation_mode=False,
            )
        )
        db.commit()
    return factory, ledger, missions, agents


def read_state(factory, mission_id):
    with factory() as db:
        mission = db.get(Mission, mission_id)
        commander = db.scalar(select(Agent).where(Agent.key == "commander"))
        sysadmin = db.scalar(select(Agent).where(Agent.key == "sysadmin"))
        return mission, commander, sysadmin


class InspectingHelper:
    def __init__(self, factory, mission_id, response):
        self.factory = factory
        self.mission_id = mission_id
        self.response = response
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        mission, commander, sysadmin = read_state(self.factory, self.mission_id)
        assert mission.status is MissionStatus.RUNNING
        assert mission.owner_agent == "sysadmin"
        assert commander.status is AgentStatus.IDLE
        assert commander.current_mission_id is None
        assert sysadmin.status is AgentStatus.WORKING
        assert sysadmin.current_mission_id == self.mission_id
        return self.response


def test_runner_processes_supported_mission_with_truthful_agent_state():
    factory, ledger, missions, agents = build_runtime()
    mission = missions.create_mission(
        title="Is Nginx running?",
        description="Read service state only.",
        owner_agent="commander",
        source="direct_user_request",
        risk=MissionRisk.GREEN,
    )
    helper = InspectingHelper(
        factory,
        mission.id,
        HelperResponse(
            True,
            HostCapability.SERVICE_STATUS,
            "nginx",
            {"active_state": "active"},
        ),
    )
    sysadmin = SysAdminService(
        safety=SafetyService(factory, ledger=ledger),
        helper=helper,
        ledger=ledger,
        allow_lists=ALLOW_LISTS,
    )

    def inspect_route(title):
        queued, commander, sysadmin_agent = read_state(factory, mission.id)
        assert queued.status is MissionStatus.QUEUED
        assert commander.status is AgentStatus.WORKING
        assert commander.current_mission_id == mission.id
        assert sysadmin_agent.status is AgentStatus.IDLE
        return route_sysadmin_mission(title)

    runner = DepartmentRunner(
        mission_service=missions,
        agent_registry=agents,
        sysadmin=sysadmin,
        router=inspect_route,
    )

    assert runner.run_once() is True

    completed, commander, sysadmin_agent = read_state(factory, mission.id)
    assert completed.status is MissionStatus.COMPLETED
    assert completed.owner_agent == "sysadmin"
    assert completed.result == {"active_state": "active"}
    assert commander.status is AgentStatus.IDLE
    assert commander.current_mission_id is None
    assert sysadmin_agent.status is AgentStatus.IDLE
    assert sysadmin_agent.current_mission_id is None
    assert len(helper.calls) == 1


def test_runner_fails_unsupported_mutating_mission_without_helper_call():
    factory, ledger, missions, agents = build_runtime()
    mission = missions.create_mission(
        title="restart nginx",
        description="Unsupported mutation.",
        owner_agent="commander",
        source="direct_user_request",
        risk=MissionRisk.GREEN,
    )
    helper = InspectingHelper(factory, mission.id, None)
    runner = DepartmentRunner(
        mission_service=missions,
        agent_registry=agents,
        sysadmin=SysAdminService(
            safety=SafetyService(factory, ledger=ledger),
            helper=helper,
            ledger=ledger,
            allow_lists=ALLOW_LISTS,
        ),
    )

    assert runner.run_once() is True

    failed, commander, sysadmin_agent = read_state(factory, mission.id)
    assert failed.status is MissionStatus.FAILED
    assert failed.error_state == {"code": "unsupported_mission"}
    assert commander.status is AgentStatus.IDLE
    assert commander.current_mission_id is None
    assert sysadmin_agent.status is AgentStatus.IDLE
    assert sysadmin_agent.current_mission_id is None
    assert helper.calls == []


def test_runner_cleans_up_sysadmin_state_after_helper_failure():
    factory, ledger, missions, agents = build_runtime()
    mission = missions.create_mission(
        title="Is Nginx running?",
        description="Read service state only.",
        owner_agent="commander",
        source="direct_user_request",
        risk=MissionRisk.GREEN,
    )
    helper = InspectingHelper(
        factory,
        mission.id,
        HelperResponse(False, HostCapability.SERVICE_STATUS, "nginx", {}, "timeout"),
    )
    runner = DepartmentRunner(
        mission_service=missions,
        agent_registry=agents,
        sysadmin=SysAdminService(
            safety=SafetyService(factory, ledger=ledger),
            helper=helper,
            ledger=ledger,
            allow_lists=ALLOW_LISTS,
        ),
    )

    assert runner.run_once() is True

    failed, _, sysadmin_agent = read_state(factory, mission.id)
    assert failed.status is MissionStatus.FAILED
    assert failed.error_state == {"code": "timeout"}
    assert sysadmin_agent.status is AgentStatus.IDLE
    assert sysadmin_agent.current_mission_id is None


def test_runner_returns_false_when_no_queued_mission_exists():
    _, _, missions, agents = build_runtime()

    class UnusedSysAdmin:
        def execute(self, **_kwargs):
            raise AssertionError("no mission should execute")

    runner = DepartmentRunner(
        mission_service=missions,
        agent_registry=agents,
        sysadmin=UnusedSysAdmin(),
    )

    assert runner.run_once() is False
