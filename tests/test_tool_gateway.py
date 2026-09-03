from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent
from ai_hq.approvals.models import ApprovalState
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.ledger.models import LedgerEventType
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService
from ai_hq.models.system_state import SystemState
from ai_hq.tool_gateway.contracts import (
    ToolAdapterError,
    ToolOutcomeState,
    ToolRequest,
)
from ai_hq.tool_gateway.registry import ToolRegistry
from ai_hq.tool_gateway.service import ToolGateway


class FakeAdapter:
    capability = "host.health"

    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def execute(self, request: ToolRequest) -> dict[str, object]:
        self.calls += 1
        if self.fail:
            raise ToolAdapterError("expected adapter failure")
        return {"ok": True, "target": request.target}


def build_gateway(*, permissions=None, risk=MissionRisk.GREEN, adapter=None):
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
    adapter = adapter or FakeAdapter()
    gateway = ToolGateway(factory, registry=ToolRegistry([adapter]))
    return gateway, adapter, mission


def request(
    mission_id: str,
    *,
    risk=MissionRisk.GREEN,
    capability="host.health",
    params=None,
    mutates_external_state=False,
):
    return ToolRequest(
        mission_id=mission_id,
        agent_key="sysadmin",
        capability=capability,
        target="ai-hq",
        risk=risk,
        params=params or {},
        conditions={},
        mutates_external_state=mutates_external_state,
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


def test_allowed_execution_records_tool_and_result_without_request_params():
    gateway, adapter, mission = build_gateway(permissions=["host.health"])
    secret_sentinel = "DO_NOT_PERSIST_SECRET_SENTINEL"

    outcome = gateway.execute(
        request(mission.id, params={"note": secret_sentinel})
    )

    assert outcome.state is ToolOutcomeState.EXECUTED
    events = gateway.ledger.for_mission(mission.id)
    relevant = [
        event
        for event in events
        if event.event_type in {
            LedgerEventType.TOOL_EXECUTED,
            LedgerEventType.RESULT_RECORDED,
        }
    ]
    assert [event.event_type for event in relevant] == [
        LedgerEventType.TOOL_EXECUTED,
        LedgerEventType.RESULT_RECORDED,
    ]
    assert secret_sentinel not in repr([event.event_data for event in relevant])
    assert adapter.calls == 1


def test_approved_mutation_is_simulated_without_adapter_call_when_simulation_enabled():
    gateway, adapter, mission = build_gateway(
        permissions=["host.health"], risk=MissionRisk.AMBER
    )
    proposed = request(
        mission.id,
        risk=MissionRisk.AMBER,
        mutates_external_state=True,
    )

    waiting = gateway.execute(proposed)
    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    gateway.safety.approvals.decide(waiting.approval_request_id, ApprovalState.APPROVED)
    with gateway.session_factory() as db:
        state = db.get(SystemState, 1)
        state.simulation_mode = True
        db.commit()

    simulated = gateway.execute(proposed)

    assert simulated.state is ToolOutcomeState.SIMULATED
    assert simulated.result == {"simulated": True}
    assert adapter.calls == 0
    result_events = [
        event
        for event in gateway.ledger.for_mission(mission.id)
        if event.event_type is LedgerEventType.RESULT_RECORDED
    ]
    assert result_events[-1].event_data["state"] == "simulated"


def test_explicit_adapter_failure_returns_failed_and_records_safe_result_metadata():
    failing = FakeAdapter(fail=True)
    gateway, adapter, mission = build_gateway(
        permissions=["host.health"], adapter=failing
    )
    secret_sentinel = "DO_NOT_PERSIST_FAILURE_SECRET"

    outcome = gateway.execute(
        request(mission.id, params={"note": secret_sentinel})
    )

    assert outcome.state is ToolOutcomeState.FAILED
    assert outcome.reason == "adapter_failed"
    assert adapter.calls == 1
    result = [
        event
        for event in gateway.ledger.for_mission(mission.id)
        if event.event_type is LedgerEventType.RESULT_RECORDED
    ][-1]
    assert result.event_data == {
        "capability": "host.health",
        "target": "ai-hq",
        "state": "failed",
    }
    assert secret_sentinel not in repr(result.event_data)
