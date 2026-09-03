from ai_hq.tool_gateway.service import ToolGateway
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService
from ai_hq.models.system_state import SystemState
from ai_hq.tool_gateway.contracts import ToolOutcomeState, ToolRequest
from ai_hq.tool_gateway.registry import ToolRegistry


class FakeAdapter:
    capability = "host.health"

    def __init__(self):
        self.calls = 0

    def execute(self, request: ToolRequest) -> dict[str, object]:
        self.calls += 1
        return {"ok": True, "target": request.target}


def build_gateway(*, permissions=None, risk=MissionRisk.GREEN):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(
            SystemState(
                id=1,
                operating_mode=OperatingMode.NORMAL.value,
                simulation_mode=False,
            )
        )
        db.add(
            Agent(
                key="sysadmin",
                display_name="SysAdmin",
                role="Restricted systems operator",
                capabilities=["host.health"],
                permissions=list(permissions or []),
            )
        )
        db.commit()
    mission = MissionService(factory).create_mission(
        title="Gateway test",
        description="Test controlled execution.",
        owner_agent="sysadmin",
        source="test",
        priority="normal",
        risk=risk,
    )
    adapter = FakeAdapter()
    gateway = ToolGateway(factory, registry=ToolRegistry([adapter]))
    return gateway, adapter, mission


def request(mission_id: str, *, risk=MissionRisk.GREEN, capability="host.health"):
    return ToolRequest(
        mission_id=mission_id,
        agent_key="sysadmin",
        capability=capability,
        target="ai-hq",
        risk=risk,
        params={},
        conditions={},
        mutates_external_state=False,
    )


def test_missing_permission_fails_closed_without_invoking_adapter():
    gateway, adapter, mission = build_gateway()

    outcome = gateway.execute(request(mission.id))

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert outcome.reason == "permission_denied"
    assert adapter.calls == 0


def test_green_read_only_action_executes_with_exact_permission():
    gateway, adapter, mission = build_gateway(permissions=["host.health"])

    outcome = gateway.execute(request(mission.id))

    assert outcome.state is ToolOutcomeState.EXECUTED
    assert outcome.result == {"ok": True, "target": "ai-hq"}
    assert adapter.calls == 1


def test_missing_adapter_fails_closed_without_prefix_or_wildcard_fallback():
    gateway, adapter, mission = build_gateway(permissions=["host.health.extra"])

    outcome = gateway.execute(request(mission.id, capability="host.health.extra"))

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert outcome.reason == "adapter_unavailable"
    assert adapter.calls == 0


def test_amber_action_waits_for_approval_without_invoking_adapter():
    gateway, adapter, mission = build_gateway(
        permissions=["host.health"], risk=MissionRisk.AMBER
    )

    outcome = gateway.execute(request(mission.id, risk=MissionRisk.AMBER))

    assert outcome.state is ToolOutcomeState.WAITING_APPROVAL
    assert outcome.approval_request_id is not None
    assert adapter.calls == 0


def test_red_action_is_blocked_even_with_permission():
    gateway, adapter, mission = build_gateway(
        permissions=["host.health"], risk=MissionRisk.RED
    )

    outcome = gateway.execute(request(mission.id, risk=MissionRisk.RED))

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert adapter.calls == 0
