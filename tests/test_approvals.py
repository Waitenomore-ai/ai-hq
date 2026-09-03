from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.approvals.models import ApprovalState
from ai_hq.approvals.service import ApprovalService, canonical_action_fingerprint
from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return MissionService(factory), ApprovalService(factory)


def create_mission(service):
    return service.create_mission(
        title="Approval test",
        description="Durable approval contract test.",
        owner_agent="sysadmin",
        source="direct_user_request",
        priority="normal",
        risk=MissionRisk.AMBER,
    )


def test_action_fingerprint_is_order_stable_and_plan_sensitive():
    first = canonical_action_fingerprint("service.restart", "uptime-kuma", {"a": 1, "b": 2})
    reordered = canonical_action_fingerprint("service.restart", "uptime-kuma", {"b": 2, "a": 1})
    changed = canonical_action_fingerprint("service.restart", "uptime-kuma", {"a": 1, "b": 3})
    assert first == reordered
    assert first != changed


def test_approval_is_bound_to_exact_action_fingerprint_and_expiry():
    missions, approvals = build_services()
    mission = create_mission(missions)
    request = approvals.create_request(
        mission_id=mission.id,
        requester_agent="sysadmin",
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.AMBER,
        action_plan={"reason": "failed health check"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    approvals.decide(request.id, ApprovalState.APPROVED)
    assert approvals.is_approved(
        mission.id,
        canonical_action_fingerprint(
            "service.restart", "uptime-kuma", {"reason": "failed health check"}
        ),
    )
    assert not approvals.is_approved(
        mission.id,
        canonical_action_fingerprint(
            "service.restart", "uptime-kuma", {"reason": "manual restart"}
        ),
    )

    expired = approvals.create_request(
        mission_id=mission.id,
        requester_agent="sysadmin",
        action="service.restart",
        target="worker",
        risk=MissionRisk.AMBER,
        action_plan={},
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    approvals.decide(expired.id, ApprovalState.APPROVED)
    assert not approvals.is_approved(mission.id, expired.action_fingerprint)


def test_scoped_rule_requires_exact_action_target_and_respects_expiry_and_count():
    _, approvals = build_services()
    rule = approvals.create_scoped_rule(
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.BLUE,
        conditions={"trigger": "failed_health_check"},
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        max_execution_count=1,
    )
    assert approvals.matching_scoped_rule(
        action="service.restart",
        target="uptime-kuma",
        risk=MissionRisk.BLUE,
        conditions={"trigger": "failed_health_check"},
    ).id == rule.id
    assert (
        approvals.matching_scoped_rule(
            action="service.restart",
            target="different-service",
            risk=MissionRisk.BLUE,
            conditions={"trigger": "failed_health_check"},
        )
        is None
    )
    approvals.consume_rule(rule.id)
    assert (
        approvals.matching_scoped_rule(
            action="service.restart",
            target="uptime-kuma",
            risk=MissionRisk.BLUE,
            conditions={"trigger": "failed_health_check"},
        )
        is None
    )


def test_red_actions_cannot_be_authorized_by_scoped_rule():
    _, approvals = build_services()
    approvals.create_scoped_rule(
        action="disk.format",
        target="/dev/sda",
        risk=MissionRisk.RED,
        conditions={},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert (
        approvals.matching_scoped_rule(
            action="disk.format",
            target="/dev/sda",
            risk=MissionRisk.RED,
            conditions={},
        )
        is None
    )
