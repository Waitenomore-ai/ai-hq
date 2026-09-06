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


def test_qa_pass_creates_real_human_approval_request():
    from ai_hq.approvals.models import ApprovalState
    from ai_hq.approvals.service import ApprovalService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="immutable-live-commit",
        summary="Developer candidate ready for QA.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="immutable-live-commit",
        result=QAResult.PASSED,
        evidence={"qa_tests": "passed"},
    )

    approvals = ApprovalService(delivery.session_factory).list_requests(
        mission_id=mission.id
    )

    assert len(approvals) == 1

    approval = approvals[0]
    persisted = delivery.get_delivery(mission.id)

    assert approval.state is ApprovalState.PENDING
    assert approval.id == persisted.approval_reference
    assert approval.mission_id == mission.id
    assert approval.requester_agent == "qa"
    assert approval.target == "immutable-live-commit"
    assert approval.action_plan["change_ref"] == "immutable-live-commit"
    assert approval.action_plan["qa_evidence"] == {"qa_tests": "passed"}


def test_operations_floor_projects_developer_and_qa_from_delivery_state():
    from ai_hq.hq.state import HQStateService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="floor-visible-commit",
        summary="Developer candidate.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    snapshot = HQStateService(delivery.session_factory).snapshot()
    rooms = {room["key"]: room for room in snapshot["rooms"]}

    assert rooms["developer"]["state"] == "IDLE"
    assert rooms["qa"]["state"] == "WORKING"
    assert rooms["qa"]["mission_title"] == mission.title

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="floor-visible-commit",
        result=QAResult.FAILED,
        evidence={"failure": "regression"},
    )

    snapshot = HQStateService(delivery.session_factory).snapshot()
    rooms = {room["key"]: room for room in snapshot["rooms"]}

    assert rooms["developer"]["state"] == "WORKING"
    assert rooms["developer"]["mission_title"] == mission.title
    assert rooms["qa"]["state"] == "IDLE"


def test_qa_pass_lights_real_approval_station_and_stops_delivery():
    from ai_hq.hq.state import HQStateService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="approval-floor-commit",
        summary="Candidate ready.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="approval-floor-commit",
        result=QAResult.PASSED,
        evidence={"qa_tests": "passed"},
    )

    snapshot = HQStateService(delivery.session_factory).snapshot()
    rooms = {room["key"]: room for room in snapshot["rooms"]}

    persisted = delivery.get_delivery(mission.id)
    persisted_mission = missions.get_mission(mission.id)

    assert persisted.stage is DeliveryStage.WAITING_APPROVAL
    assert persisted_mission.status is MissionStatus.WAITING_APPROVAL

    assert rooms["developer"]["state"] == "IDLE"
    assert rooms["qa"]["state"] == "IDLE"
    assert rooms["approvals"]["state"] == "WAITING_APPROVAL"
    assert rooms["approvals"]["count"] == 1


def test_human_approval_accepts_exact_qa_passed_change():
    from ai_hq.approvals.models import ApprovalState
    from ai_hq.approvals.service import ApprovalService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="approved-exact-commit",
        summary="Exact candidate.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="approved-exact-commit",
        result=QAResult.PASSED,
        evidence={"qa_tests": "passed"},
    )

    pending = delivery.get_delivery(mission.id)
    approval_id = pending.approval_reference

    ApprovalService(delivery.session_factory).decide(
        approval_id,
        ApprovalState.APPROVED,
    )

    decided = delivery.apply_human_decision(
        mission_id=mission.id,
        approval_reference=approval_id,
        change_ref="approved-exact-commit",
    )

    approval = ApprovalService(
        delivery.session_factory
    ).get_request(approval_id)

    assert approval.state is ApprovalState.APPROVED
    assert decided.change_ref == "approved-exact-commit"
    assert decided.approval_reference == approval_id

    # Approval is authorization only. It must not itself deploy.
    assert decided.stage is DeliveryStage.WAITING_APPROVAL
    assert missions.get_mission(
        mission.id
    ).status is MissionStatus.WAITING_APPROVAL


def test_human_rejection_returns_exact_change_to_developer():
    from ai_hq.approvals.models import ApprovalState
    from ai_hq.approvals.service import ApprovalService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="rejected-exact-commit",
        summary="Candidate requiring human review.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="rejected-exact-commit",
        result=QAResult.PASSED,
        evidence={"qa_tests": "passed"},
    )

    pending = delivery.get_delivery(mission.id)
    approval_id = pending.approval_reference

    ApprovalService(delivery.session_factory).decide(
        approval_id,
        ApprovalState.DENIED,
    )

    decided = delivery.apply_human_decision(
        mission_id=mission.id,
        approval_reference=approval_id,
        change_ref="rejected-exact-commit",
    )

    assert decided.stage is DeliveryStage.DEVELOPER
    assert decided.change_ref == "rejected-exact-commit"
    assert decided.approval_reference is None

    assert missions.get_mission(
        mission.id
    ).status is MissionStatus.RUNNING


def test_human_decision_rejects_mismatched_change_ref():
    from ai_hq.approvals.models import ApprovalState
    from ai_hq.approvals.service import ApprovalService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="real-immutable-commit",
        summary="Immutable candidate.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="real-immutable-commit",
        result=QAResult.PASSED,
        evidence={"qa_tests": "passed"},
    )

    pending = delivery.get_delivery(mission.id)
    approval_id = pending.approval_reference

    ApprovalService(delivery.session_factory).decide(
        approval_id,
        ApprovalState.APPROVED,
    )

    try:
        delivery.apply_human_decision(
            mission_id=mission.id,
            approval_reference=approval_id,
            change_ref="different-commit",
        )
    except ValueError as exc:
        assert "change_ref" in str(exc)
    else:
        raise AssertionError(
            "mismatched change_ref was incorrectly accepted"
        )


def test_human_decision_rejects_wrong_approval_reference():
    from ai_hq.approvals.models import ApprovalState
    from ai_hq.approvals.service import ApprovalService

    missions, delivery = build_services()
    mission = create_mission(missions)

    delivery.submit_developer_proposal(
        mission_id=mission.id,
        change_ref="approval-bound-commit",
        summary="Approval-bound candidate.",
        changed_files=["src/ai_hq/example.py"],
        evidence={"developer_tests": "passed"},
    )

    delivery.record_qa_result(
        mission_id=mission.id,
        change_ref="approval-bound-commit",
        result=QAResult.PASSED,
        evidence={"qa_tests": "passed"},
    )

    pending = delivery.get_delivery(mission.id)

    ApprovalService(delivery.session_factory).decide(
        pending.approval_reference,
        ApprovalState.APPROVED,
    )

    try:
        delivery.apply_human_decision(
            mission_id=mission.id,
            approval_reference="wrong-approval-reference",
            change_ref="approval-bound-commit",
        )
    except ValueError as exc:
        assert "approval" in str(exc).lower()
    else:
        raise AssertionError(
            "wrong approval reference was incorrectly accepted"
        )
