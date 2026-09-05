from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent
from ai_hq.approvals.models import ScopedApprovalRule
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService
from ai_hq.models.system_state import SystemState
from ai_hq.tool_gateway.contracts import ToolOutcomeState, ToolRequest
from ai_hq.tool_gateway.registry import ToolRegistry
from ai_hq.tool_gateway.service import ToolGateway


RECOVERY_CONDITIONS = {
    "recovery_policy": "dripvid-2.90",
    "component": "app",
}


class FakeRecoverAdapter:
    capability = "service.recover"

    def __init__(self):
        self.calls = 0

    def execute(self, request: ToolRequest) -> dict[str, object]:
        self.calls += 1
        return {
            "recovered": True,
            "component": request.params["component"],
        }


def build_gateway(*, mode=OperatingMode.NORMAL, simulation=False):
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
                operating_mode=mode.value,
                simulation_mode=simulation,
            )
        )
        db.add(
            Agent(
                key="sysadmin",
                display_name="SysAdmin",
                role="Restricted systems operator",
                capabilities=["service.recover"],
                permissions=["service.recover"],
            )
        )
        db.commit()

    mission = MissionService(factory).create_mission(
        title="Recover DripVid app",
        description="Bounded automatic recovery test.",
        owner_agent="sysadmin",
        source="recovery_observer",
        priority="high",
        risk=MissionRisk.BLUE,
    )
    adapter = FakeRecoverAdapter()
    gateway = ToolGateway(factory, registry=ToolRegistry([adapter]))
    return gateway, adapter, mission, factory


def recovery_request(mission_id, *, conditions=None):
    return ToolRequest(
        mission_id=mission_id,
        agent_key="sysadmin",
        capability="service.recover",
        target="dripvid",
        risk=MissionRisk.BLUE,
        params={"component": "app"},
        conditions=conditions or RECOVERY_CONDITIONS,
        mutates_external_state=True,
    )


def create_rule(gateway, *, action="service.recover", target="dripvid", risk=MissionRisk.BLUE,
                conditions=None, expires_delta=timedelta(hours=1), max_execution_count=2):
    return gateway.safety.approvals.create_scoped_rule(
        action=action,
        target=target,
        risk=risk,
        conditions=conditions or RECOVERY_CONDITIONS,
        expires_at=datetime.now(UTC) + expires_delta,
        max_execution_count=max_execution_count,
    )


def execution_count(factory, rule_id):
    with factory() as db:
        return db.get(ScopedApprovalRule, rule_id).execution_count


def test_recovery_without_exact_scoped_rule_waits_for_approval_without_adapter_call():
    gateway, adapter, mission, _ = build_gateway()

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.WAITING_APPROVAL
    assert outcome.approval_request_id is not None
    assert adapter.calls == 0


def test_exact_scoped_rule_is_consumed_immediately_before_real_recovery():
    gateway, adapter, mission, factory = build_gateway()
    rule = create_rule(gateway)

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.EXECUTED
    assert outcome.result == {"recovered": True, "component": "app"}
    assert adapter.calls == 1
    assert execution_count(factory, rule.id) == 1


def test_each_real_recovery_consumes_one_execution_from_scoped_rule():
    gateway, adapter, mission, factory = build_gateway()
    rule = create_rule(gateway, max_execution_count=2)
    proposed = recovery_request(mission.id)

    first = gateway.execute(proposed)
    second = gateway.execute(proposed)
    third = gateway.execute(proposed)

    assert first.state is ToolOutcomeState.EXECUTED
    assert second.state is ToolOutcomeState.EXECUTED
    assert third.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 2
    assert execution_count(factory, rule.id) == 2


def test_wrong_action_target_risk_or_conditions_do_not_authorize_recovery():
    variants = [
        {"action": "service.restart"},
        {"target": "ai-hq"},
        {"risk": MissionRisk.GREEN},
        {"conditions": {"recovery_policy": "wrong", "component": "app"}},
    ]

    for variant in variants:
        gateway, adapter, mission, _ = build_gateway()
        create_rule(gateway, **variant)

        outcome = gateway.execute(recovery_request(mission.id))

        assert outcome.state is ToolOutcomeState.WAITING_APPROVAL
        assert adapter.calls == 0


def test_expired_scoped_rule_does_not_authorize_recovery():
    gateway, adapter, mission, _ = build_gateway()
    create_rule(gateway, expires_delta=timedelta(seconds=-1))

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 0


def test_exhausted_scoped_rule_does_not_authorize_recovery():
    gateway, adapter, mission, factory = build_gateway()
    rule = create_rule(gateway, max_execution_count=1)
    with factory() as db:
        persisted = db.get(ScopedApprovalRule, rule.id)
        persisted.execution_count = 1
        db.commit()

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.WAITING_APPROVAL
    assert adapter.calls == 0


def test_freeze_blocks_recovery_even_with_scoped_rule():
    gateway, adapter, mission, factory = build_gateway(mode=OperatingMode.FREEZE)
    rule = create_rule(gateway)

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert adapter.calls == 0
    assert execution_count(factory, rule.id) == 0


def test_safe_mode_blocks_real_recovery_even_with_scoped_rule():
    gateway, adapter, mission, factory = build_gateway(mode=OperatingMode.SAFE)
    rule = create_rule(gateway)

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert adapter.calls == 0
    assert execution_count(factory, rule.id) == 0


def test_simulation_never_calls_adapter_or_consumes_scoped_rule():
    gateway, adapter, mission, factory = build_gateway(simulation=True)
    rule = create_rule(gateway)

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.SIMULATED
    assert outcome.result == {"simulated": True}
    assert adapter.calls == 0
    assert execution_count(factory, rule.id) == 0


def test_scoped_rule_consumption_failure_blocks_before_adapter(monkeypatch):
    gateway, adapter, mission, factory = build_gateway()
    rule = create_rule(gateway)

    def fail_consumption(_rule_id):
        raise ValueError("simulated concurrent exhaustion")

    monkeypatch.setattr(
        gateway.safety.approvals,
        "consume_rule",
        fail_consumption,
    )

    outcome = gateway.execute(recovery_request(mission.id))

    assert outcome.state is ToolOutcomeState.BLOCKED
    assert outcome.reason == "scoped_rule_consumption_failed"
    assert adapter.calls == 0
    assert execution_count(factory, rule.id) == 0
