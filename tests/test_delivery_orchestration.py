from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.db import Base
from ai_hq.missions.models import MissionRisk, MissionStatus
from ai_hq.missions.service import MissionService

# These imports intentionally describe the backend contract we are building.
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.delivery.service import DeliveryService


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    return MissionService(factory), DeliveryService(factory)


def create_mission(missions):
    return missions.create_mission(
        title="Implement requested AI HQ change",
        description="Developer implements; QA verifies; human approves.",
        owner_agent="sysadmin",
        source="direct_user_request",
        priority="normal",
        risk=MissionRisk.GREEN,
    )


def test_developer_proposal_is_persisted_against_exact_mission():
    missions, delivery = build_services()
    mission = create_mission(missions)

    proposal = delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="commit-abc123",
        summary="Implemented requested change.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"tests": "12 passed"},
    )

    persisted = delivery.get_delivery(mission.id)

    assert proposal.mission_id == mission.id
    assert persisted.mission_id == mission.id
    assert persisted.change_ref == "commit-abc123"
    assert persisted.stage is DeliveryStage.QA
    assert persisted.developer_evidence == {"tests": "12 passed"}


def test_qa_failure_returns_exact_proposal_to_developer_without_human_approval():
    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="commit-failing",
        summary="Candidate implementation.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"tests": "developer tests passed"},
    )

    result = delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="commit-failing",
        result=QAResult.FAILED,
        evidence={"failure": "regression test failed"},
    )

    persisted = delivery.get_delivery(mission.id)
    persisted_mission = missions.get_mission(mission.id)

    assert result.qa_result is QAResult.FAILED
    assert persisted.stage is DeliveryStage.DEVELOPER
    assert persisted.qa_evidence == {"failure": "regression test failed"}
    assert persisted.approval_reference is None
    assert persisted_mission.status is not MissionStatus.WAITING_APPROVAL


def test_qa_pass_moves_exact_change_to_human_approval():
    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="commit-good",
        summary="Candidate implementation.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"tests": "developer tests passed"},
    )

    result = delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="commit-good",
        result=QAResult.PASSED,
        evidence={"pytest": "461 passed"},
    )

    persisted = delivery.get_delivery(mission.id)
    persisted_mission = missions.get_mission(mission.id)

    assert result.qa_result is QAResult.PASSED
    assert persisted.stage is DeliveryStage.WAITING_APPROVAL
    assert persisted.change_ref == "commit-good"
    assert persisted.qa_evidence == {"pytest": "461 passed"}
    assert persisted.approval_reference is not None
    assert persisted_mission.status is MissionStatus.WAITING_APPROVAL


def test_qa_cannot_approve_different_change_than_developer_submitted():
    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="commit-approved-for-qa",
        summary="Candidate implementation.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"tests": "passed"},
    )

    try:
        delivery.record_qa_result(
            mission_id=mission.id,
            change_ref="different-commit",
            result=QAResult.PASSED,
            evidence={"pytest": "passed"},
        )
    except ValueError as exc:
        assert "change_ref" in str(exc)
    else:
        raise AssertionError(
            "QA must never pass a different change than Developer submitted"
        )


def test_human_approval_is_bound_to_immutable_change_reference():
    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="immutable-commit",
        summary="Ready candidate.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="immutable-commit",
        result=QAResult.PASSED,
        evidence={"pytest": "passed"},
    )

    approval = delivery.get_delivery(mission.id)

    assert approval.stage is DeliveryStage.WAITING_APPROVAL
    assert approval.change_ref == "immutable-commit"
    assert approval.approval_reference
