from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.approvals.models import ApprovalState
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.ledger.models import LedgerEventType
from ai_hq.ledger.service import OperationsLedger
from ai_hq.missions.models import MissionRisk, MissionStatus
from ai_hq.missions.service import MissionService
from ai_hq.models.system_state import SystemState
from ai_hq.safety.policy import Decision
from ai_hq.safety.service import SafetyService


def build_services(*, mode=OperatingMode.NORMAL, simulation=False):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(SystemState(id=1, operating_mode=mode.value, simulation_mode=simulation))
        db.commit()
    ledger = OperationsLedger(factory)
    missions = MissionService(factory, ledger=ledger)
    safety = SafetyService(factory, ledger=ledger)
    return factory, missions, safety, ledger


def create_mission(missions, risk=MissionRisk.AMBER):
    return missions.create_mission(
        title="Safety test",
        description="Verify policy, approval and audit integration.",
        owner_agent="sysadmin",
        source="test",
        priority="normal",
        risk=risk,
    )


def test_amber_action_creates_one_pending_action_bound_approval_and_audit_chain():
    _factory, missions, safety, ledger = build_services()
    mission = create_mission(missions)

    result = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "failed health check"},
        conditions={},
        mutates_external_state=True,
    )
    again = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "failed health check"},
        conditions={},
        mutates_external_state=True,
    )

    assert result.decision is Decision.REQUIRE_APPROVAL
    assert result.mission_status is MissionStatus.WAITING_APPROVAL
    assert result.approval_request_id == again.approval_request_id
    event_types = [event.event_type for event in ledger.for_mission(mission.id)]
    assert LedgerEventType.ACTION_PROPOSED in event_types
    assert LedgerEventType.PERMISSION_CHECKED in event_types
    assert LedgerEventType.RISK_CHECKED in event_types
    assert LedgerEventType.APPROVAL_RECORDED in event_types


def test_exact_approval_allows_same_plan_but_not_changed_plan():
    _factory, missions, safety, _ledger = build_services()
    mission = create_mission(missions)
    waiting = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "failed health check"},
        conditions={},
        mutates_external_state=True,
    )
    safety.approvals.decide(waiting.approval_request_id, ApprovalState.APPROVED)

    allowed = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "failed health check"},
        conditions={},
        mutates_external_state=True,
    )
    changed = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "manual restart"},
        conditions={},
        mutates_external_state=True,
    )
    assert allowed.decision is Decision.ALLOW
    assert changed.decision is Decision.REQUIRE_APPROVAL
    assert changed.approval_request_id != waiting.approval_request_id


def test_safe_freeze_and_missing_state_fail_closed():
    factory, missions, safety, _ledger = build_services(mode=OperatingMode.SAFE, simulation=False)
    mission = create_mission(missions, MissionRisk.GREEN)
    safe = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.GREEN,
        action_plan={},
        conditions={},
        mutates_external_state=True,
    )
    assert safe.decision is Decision.BLOCK

    with factory() as db:
        state = db.get(SystemState, 1)
        state.operating_mode = OperatingMode.FREEZE.value
        db.commit()
    frozen = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="system.health",
        target="ai-hq",
        risk=MissionRisk.GREEN,
        action_plan={},
        conditions={},
        mutates_external_state=False,
    )
    assert frozen.decision is Decision.BLOCK

    with factory() as db:
        db.delete(db.get(SystemState, 1))
        db.commit()
    missing = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="system.health",
        target="ai-hq",
        risk=MissionRisk.GREEN,
        action_plan={},
        conditions={},
        mutates_external_state=False,
    )
    assert missing.decision is Decision.BLOCK


def test_active_blue_rule_can_authorize_but_red_never_can():
    _factory, missions, safety, _ledger = build_services()
    mission = create_mission(missions, MissionRisk.BLUE)
    safety.approvals.create_scoped_rule(
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.BLUE,
        conditions={"trigger": "failed_health_check"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_execution_count=1,
    )
    blue = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.BLUE,
        action_plan={"reason": "health automation"},
        conditions={"trigger": "failed_health_check"},
        mutates_external_state=True,
    )
    red = safety.evaluate(
        mission_id=mission.id,
        agent_key="sysadmin",
        action="disk.format",
        target="/dev/sda",
        risk=MissionRisk.RED,
        action_plan={},
        conditions={},
        mutates_external_state=True,
    )
    assert blue.decision is Decision.ALLOW
    assert red.decision is Decision.BLOCK
