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


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return MissionService(factory), DeliveryService(factory)


def approved_delivery():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Publish verified candidate",
        description="Publish only after QA and human approval.",
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
    return missions, deliveries, mission, waiting


def record(deliveries, mission_id, **overrides):
    values = {
        "mission_id": mission_id,
        "change_ref": CHANGE_REF,
        "branch_name": BRANCH,
        "commit_sha": COMMIT,
        "tree_sha": TREE,
    }
    values.update(overrides)
    return deliveries.record_publication(**values)


def test_record_publication_persists_exact_approved_identity():
    _, deliveries, mission, _ = approved_delivery()

    published = record(deliveries, mission.id)
    persisted = deliveries.get_delivery(mission.id)

    assert published.stage is DeliveryStage.WAITING_APPROVAL
    assert published.qa_result is QAResult.PASSED
    assert persisted.published_branch == BRANCH
    assert persisted.published_commit == COMMIT
    assert persisted.published_tree == TREE
    assert persisted.published_at is not None


def test_record_publication_is_idempotent_only_for_exact_same_identity():
    _, deliveries, mission, _ = approved_delivery()

    first = record(deliveries, mission.id)
    first_published_at = first.published_at
    second = record(deliveries, mission.id)

    assert second.published_branch == BRANCH
    assert second.published_commit == COMMIT
    assert second.published_tree == TREE
    assert second.published_at == first_published_at

    for field, value in (
        ("branch_name", "ai-hq/candidate/different-aaaaaaaaaaaa"),
        ("commit_sha", "d" * 40),
        ("tree_sha", "e" * 40),
    ):
        try:
            record(deliveries, mission.id, **{field: value})
        except ValueError as exc:
            assert "publication" in str(exc).lower()
        else:
            raise AssertionError("mismatched publication replay was accepted")


def test_record_publication_rejects_wrong_change_ref():
    _, deliveries, mission, _ = approved_delivery()

    try:
        record(deliveries, mission.id, change_ref="sha256:" + "f" * 64)
    except ValueError as exc:
        assert "change_ref" in str(exc)
    else:
        raise AssertionError("wrong change_ref was accepted")


def test_record_publication_rejects_pending_human_approval():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Pending publication",
        description="Pending approval must block publication.",
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
    deliveries.record_qa_result(
        mission_id=mission.id,
        change_ref=CHANGE_REF,
        result=QAResult.PASSED,
        evidence={"qa": "passed"},
    )

    try:
        record(deliveries, mission.id)
    except ValueError as exc:
        assert "approval" in str(exc).lower()
    else:
        raise AssertionError("pending approval allowed publication")


def test_record_publication_rejects_non_waiting_or_non_qa_passed_delivery():
    missions, deliveries = build_services()
    mission = missions.create_mission(
        title="Unverified publication",
        description="QA must pass before publication.",
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
        raise AssertionError("non-QA-passed delivery allowed publication")
