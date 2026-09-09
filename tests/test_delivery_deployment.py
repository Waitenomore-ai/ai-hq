from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.approvals.models import ApprovalState
from ai_hq.approvals.service import ApprovalService
from ai_hq.db import Base
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.delivery.service import DeliveryService
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService


CHANGE_REF = "sha256:" + "a" * 64
BRANCH = "ai-hq/candidate/111111111111-aaaaaaaaaaaa"
COMMIT = "b" * 40
TREE = "c" * 40
RELEASE_ID = "dripvid-2026-09-09.rc1"
PRIOR_RELEASE_ID = "dripvid-2026-09-08.prod"


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return MissionService(factory), DeliveryService(factory)


def approved_published_delivery():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Deploy verified candidate",
        description="Deploy only after QA, publication and human approval.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    deliveries.submit_developer_proposal(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        summary="Verified candidate",
        changed_files=["src/ai_hq/example.py"],
        evidence={"verification": "candidate_identity_verified"},
    )
    waiting = deliveries.record_qa_result(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        result=QAResult.PASSED,
        evidence={"qa": "passed"},
    )
    ApprovalService(deliveries.session_factory).decide(
        waiting.approval_reference,
        ApprovalState.APPROVED,
    )
    deliveries.record_publication(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        branch_name=BRANCH,
        commit_sha=COMMIT,
        tree_sha=TREE,
    )
    return missions, deliveries, mission, waiting


def record(deliveries, mission_id, **overrides):
    values = {
        "mission_id": mission_id,
        "change_ref": CHANGE_REF,
        "release_id": RELEASE_ID,
        "prior_release_id": PRIOR_RELEASE_ID,
    }
    values.update(overrides)
    return deliveries.record_deployment(**values)


def test_record_deployment_persists_exact_approved_release():
    _, deliveries, mission, _ = approved_published_delivery()

    deployed = record(deliveries, mission.id)
    persisted = deliveries.get_delivery(mission.id)

    assert deployed.stage is DeliveryStage.WAITING_APPROVAL
    assert deployed.qa_result is QAResult.PASSED
    assert persisted.published_branch == BRANCH
    assert persisted.published_commit == COMMIT
    assert persisted.deployment_release_id == RELEASE_ID
    assert persisted.deployment_prior_release_id == PRIOR_RELEASE_ID
    assert persisted.deployed_at is not None


def test_record_deployment_is_idempotent_only_for_exact_same_release():
    _, deliveries, mission, _ = approved_published_delivery()

    first = record(deliveries, mission.id)
    first_deployed_at = first.deployed_at
    second = record(deliveries, mission.id)

    assert second.deployment_release_id == RELEASE_ID
    assert second.deployment_prior_release_id == PRIOR_RELEASE_ID
    assert second.deployed_at == first_deployed_at

    for field, value in (
        ("release_id", "other-release"),
        ("prior_release_id", "other-prior"),
    ):
        try:
            record(deliveries, mission.id, **{field: value})
        except ValueError as exc:
            assert "deployment" in str(exc).lower()
        else:
            raise AssertionError("mismatched deployment replay was accepted")


def test_record_deployment_rejects_wrong_change_ref():
    _, deliveries, mission, _ = approved_published_delivery()

    try:
        record(deliveries, mission.id, change_ref="sha256:" + "f" * 64)
    except ValueError as exc:
        assert "change_ref" in str(exc)
    else:
        raise AssertionError("wrong change_ref was accepted")


def test_record_deployment_rejects_pending_human_approval():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Pending deployment",
        description="Pending approval must block deployment.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    proposals = deliveries.session_factory
    deliveries.submit_developer_proposal(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        summary="Candidate",
        changed_files=["src/ai_hq/example.py"],
        evidence={"verification": "candidate_identity_verified"},
    )
    deliveries.record_qa_result(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        result=QAResult.PASSED,
        evidence={"qa": "passed"},
    )

    from ai_hq.delivery.models import Delivery

    with proposals() as db:
        delivery = (
            db.query(Delivery)
            .filter(Delivery.mission_id == mission.id)
            .one()
        )
        delivery.published_branch = BRANCH
        delivery.published_commit = COMMIT
        delivery.published_tree = TREE
        db.commit()

    try:
        record(deliveries, mission.id)
    except ValueError as exc:
        assert "approval" in str(exc).lower()
    else:
        raise AssertionError("pending approval allowed deployment")


def test_record_deployment_requires_publication_first():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Unpublished deployment",
        description="Deployment must follow publication.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    deliveries.submit_developer_proposal(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        summary="Candidate",
        changed_files=["src/ai_hq/example.py"],
        evidence={"verification": "candidate_identity_verified"},
    )
    waiting = deliveries.record_qa_result(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        result=QAResult.PASSED,
        evidence={"qa": "passed"},
    )
    ApprovalService(deliveries.session_factory).decide(
        waiting.approval_reference,
        ApprovalState.APPROVED,
    )

    try:
        record(deliveries, mission.id)
    except ValueError as exc:
        assert "published" in str(exc).lower()
    else:
        raise AssertionError("unpublished delivery allowed deployment")


def test_record_deployment_rejects_unsafe_release_id():
    _, deliveries, mission, _ = approved_published_delivery()

    for unsafe in (
        "dripvid release",
        "dripvid/../../etc",
        "a" * 129,
        "release-\u00e9",
    ):
        try:
            record(deliveries, mission.id, release_id=unsafe)
        except ValueError as exc:
            assert "release" in str(exc).lower()
        else:
            raise AssertionError("unsafe release id was accepted")


def test_record_deployment_rejects_non_waiting_or_qa_failed_delivery():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Unverified deployment",
        description="QA must pass before deployment.",
        owner_agent="developer",
        source="hq_chat_code_change",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    deliveries.submit_developer_proposal(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        summary="Candidate",
        changed_files=["src/ai_hq/example.py"],
        evidence={"verification": "candidate_identity_verified"},
    )

    try:
        record(deliveries, mission.id)
    except ValueError as exc:
        assert "qa" in str(exc).lower() or "waiting" in str(exc).lower()
    else:
        raise AssertionError("non-QA-passed delivery allowed deployment")