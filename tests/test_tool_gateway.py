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


class FakeRestartAdapter:
    capability = "service.restart"

    def __init__(self):
        self.calls = 0

    def execute(self, request: ToolRequest) -> dict[str, object]:
        self.calls += 1
        return {"restarted": request.target}


def test_stage2_restart_requires_exact_permission():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["*"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    outcome = gateway.execute(
        request(
            mission.id,
            capability="service.restart",
            mutates_external_state=True,
        )
    )

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert outcome.reason == "permission_denied"
    assert adapter.calls == 0


def test_stage2_restart_requires_approval_before_adapter():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["service.restart"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    proposed = request(
        mission.id,
        capability="service.restart",
        mutates_external_state=True,
    )

    outcome = gateway.execute(proposed)

    assert outcome.state is ToolOutcomeState.WAITING_APPROVAL
    assert outcome.approval_request_id is not None
    assert adapter.calls == 0


def test_stage2_approved_restart_executes_once():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["service.restart"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    proposed = request(
        mission.id,
        capability="service.restart",
        mutates_external_state=True,
    )

    waiting = gateway.execute(proposed)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    outcome = gateway.execute(proposed)

    assert outcome.state is ToolOutcomeState.EXECUTED
    assert outcome.result == {"restarted": "ai-hq"}
    assert adapter.calls == 1


def test_stage2_restart_simulation_never_calls_adapter():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["service.restart"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    proposed = request(
        mission.id,
        capability="service.restart",
        mutates_external_state=True,
    )

    waiting = gateway.execute(proposed)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    with gateway.session_factory() as db:
        state = db.get(SystemState, 1)
        state.simulation_mode = True
        db.commit()

    outcome = gateway.execute(proposed)

    assert outcome.state is ToolOutcomeState.SIMULATED
    assert outcome.result == {"simulated": True}
    assert adapter.calls == 0


def test_stage2_restart_audit_chain_is_reconstructable():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["service.restart"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    proposed = request(
        mission.id,
        capability="service.restart",
        mutates_external_state=True,
    )

    waiting = gateway.execute(proposed)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    outcome = gateway.execute(proposed)

    assert outcome.state is ToolOutcomeState.EXECUTED
    assert adapter.calls == 1

    events = gateway.ledger.for_mission(mission.id)

    event_types = [event.event_type for event in events]

    assert LedgerEventType.ACTION_PROPOSED in event_types
    assert LedgerEventType.PERMISSION_CHECKED in event_types
    assert LedgerEventType.RISK_CHECKED in event_types
    assert LedgerEventType.APPROVAL_RECORDED in event_types
    assert LedgerEventType.TOOL_EXECUTED in event_types
    assert LedgerEventType.RESULT_RECORDED in event_types

    proposed_events = [
        event
        for event in events
        if event.event_type is LedgerEventType.ACTION_PROPOSED
    ]

    assert proposed_events[-1].event_data["action"] == "service.restart"
    assert proposed_events[-1].event_data["target"] == "ai-hq"
    assert proposed_events[-1].agent_key == "sysadmin"

    sequences = [event.sequence for event in events]
    assert sequences == sorted(sequences)


def test_stage2_operational_audit_does_not_store_request_secrets():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["service.restart"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    secret = "STAGE2_SECRET_MUST_NOT_ENTER_LEDGER"

    proposed = request(
        mission.id,
        capability="service.restart",
        params={"secret": secret},
        mutates_external_state=True,
    )

    waiting = gateway.execute(proposed)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 0

    events = gateway.ledger.for_mission(mission.id)

    assert secret not in repr(
        [event.event_data for event in events]
    )


def test_stage2_simulation_is_visible_in_audit_result():
    adapter = FakeRestartAdapter()
    gateway, adapter, mission = build_gateway(
        permissions=["service.restart"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    proposed = request(
        mission.id,
        capability="service.restart",
        mutates_external_state=True,
    )

    waiting = gateway.execute(proposed)

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    with gateway.session_factory() as db:
        state = db.get(SystemState, 1)
        state.simulation_mode = True
        db.commit()

    outcome = gateway.execute(proposed)

    assert outcome.state is ToolOutcomeState.SIMULATED
    assert adapter.calls == 0

    result_events = [
        event
        for event in gateway.ledger.for_mission(mission.id)
        if event.event_type is LedgerEventType.RESULT_RECORDED
    ]

    assert result_events[-1].event_data["state"] == "simulated"
    assert result_events[-1].event_data["capability"] == "service.restart"
    assert result_events[-1].event_data["target"] == "ai-hq"


class FakeDeploymentAdapter:
    def __init__(self, capability):
        self.capability = capability
        self.calls = 0

    def execute(self, request: ToolRequest) -> dict[str, object]:
        self.calls += 1
        return {
            "target": request.target,
            "capability": request.capability,
            "executed": True,
        }


def test_deployment_deploy_requires_exact_permission():
    adapter = FakeDeploymentAdapter("deployment.deploy")
    gateway, adapter, mission = build_gateway(
        permissions=["*"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    outcome = gateway.execute(
        request(
            mission.id,
            capability="deployment.deploy",
            mutates_external_state=True,
        )
    )

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert outcome.reason == "permission_denied"
    assert adapter.calls == 0


def test_deployment_deploy_requires_approval_before_execution():
    adapter = FakeDeploymentAdapter("deployment.deploy")
    gateway, adapter, mission = build_gateway(
        permissions=["deployment.deploy"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    deployment_request = request(
        mission.id,
        capability="deployment.deploy",
        mutates_external_state=True,
    )

    waiting = gateway.execute(deployment_request)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert waiting.approval_request_id is not None
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    executed = gateway.execute(deployment_request)

    assert executed.state is ToolOutcomeState.EXECUTED
    assert adapter.calls == 1


def test_deployment_deploy_simulation_never_executes_adapter():
    adapter = FakeDeploymentAdapter("deployment.deploy")
    gateway, adapter, mission = build_gateway(
        permissions=["deployment.deploy"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    deployment_request = request(
        mission.id,
        capability="deployment.deploy",
        mutates_external_state=True,
    )

    waiting = gateway.execute(deployment_request)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert waiting.approval_request_id is not None
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    with gateway.session_factory() as db:
        state = db.get(SystemState, 1)
        state.simulation_mode = True
        db.commit()

    simulated = gateway.execute(deployment_request)

    assert simulated.state is ToolOutcomeState.SIMULATED
    assert adapter.calls == 0


def test_deployment_rollback_requires_approval_before_execution():
    adapter = FakeDeploymentAdapter("deployment.rollback")
    gateway, adapter, mission = build_gateway(
        permissions=["deployment.rollback"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    rollback_request = request(
        mission.id,
        capability="deployment.rollback",
        params={"release_id": "release-2.83.0"},
        mutates_external_state=True,
    )

    waiting = gateway.execute(rollback_request)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert waiting.approval_request_id is not None
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    executed = gateway.execute(rollback_request)

    assert executed.state is ToolOutcomeState.EXECUTED
    assert adapter.calls == 1


def test_deployment_rollback_simulation_never_executes_adapter():
    adapter = FakeDeploymentAdapter("deployment.rollback")
    gateway, adapter, mission = build_gateway(
        permissions=["deployment.rollback"],
        risk=MissionRisk.GREEN,
        adapter=adapter,
    )

    rollback_request = request(
        mission.id,
        capability="deployment.rollback",
        params={"release_id": "release-2.83.0"},
        mutates_external_state=True,
    )

    waiting = gateway.execute(rollback_request)

    assert waiting.state is ToolOutcomeState.WAITING_APPROVAL
    assert waiting.approval_request_id is not None
    assert adapter.calls == 0

    gateway.safety.approvals.decide(
        waiting.approval_request_id,
        ApprovalState.APPROVED,
    )

    with gateway.session_factory() as db:
        state = db.get(SystemState, 1)
        state.simulation_mode = True
        db.commit()

    simulated = gateway.execute(rollback_request)

    assert simulated.state is ToolOutcomeState.SIMULATED
    assert adapter.calls == 0
