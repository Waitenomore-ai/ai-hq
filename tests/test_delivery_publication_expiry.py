from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.approvals.models import ApprovalRequest, ApprovalState
from ai_hq.approvals.service import ApprovalService
from ai_hq.db import Base
from ai_hq.delivery.models import QAResult
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService


CHANGE_REF = "sha256:" + "a" * 64


def test_record_publication_rejects_approved_but_expired_approval():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    missions = MissionService(factory)
    deliveries = DeliveryService(factory)

    mission = missions.create_mission(
        title="Expired publication",
        description="Expired approval must not authorize publication.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    deliveries.submit_developer_proposal(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        summary="Verified candidate",
        changed_files=["src/example.py"],
        evidence={"verification": "candidate_identity_verified"},
    )
    waiting = deliveries.record_qa_result(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        result=QAResult.PASSED,
        evidence={"qa": "passed"},
    )
    ApprovalService(factory).decide(
        waiting.approval_reference,
        ApprovalState.APPROVED,
    )

    with factory() as db:
        approval = db.get(ApprovalRequest, waiting.approval_reference)
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with pytest.raises(ValueError, match="expired|approval"):
        deliveries.record_publication(
            mission_id=mission.id,
            change_ref=CHANGE_REF,
            branch_name="ai-hq/candidate/111111111111-aaaaaaaaaaaa",
            commit_sha="b" * 40,
            tree_sha="c" * 40,
        )
