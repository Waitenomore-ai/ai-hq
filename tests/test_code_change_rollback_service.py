from dataclasses import dataclass

import pytest

from ai_hq.code_changes.rollbacker import RolledBackRelease
from ai_hq.code_changes.service import CodeChangeService
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.missions.models import MissionStatus


CHANGE_REF = "sha256:" + "a" * 64
BRANCH = "ai-hq/candidate/111111111111-aaaaaaaaaaaa"
COMMIT = "b" * 40
TREE = "c" * 40
RELEASE_ID = "dripvid-2026-09-09.rc1"
PRIOR_RELEASE_ID = "dripvid-2026-09-08.prod"


@dataclass
class Mission:
    id: str = "mission-1"
    owner_agent: str = "developer"
    source: str = "hq_chat_code_change"
    objectives: list[str] | None = None
    status: MissionStatus = MissionStatus.WAITING_APPROVAL


@dataclass
class Delivery:
    mission_id: str = "mission-1"
    change_ref: str = CHANGE_REF
    summary: str = "Verified change"
    changed_files: list[str] | None = None
    developer_evidence: dict | None = None
    qa_result: QAResult | None = QAResult.PASSED
    qa_evidence: dict | None = None
    stage: DeliveryStage = DeliveryStage.WAITING_APPROVAL
    approval_reference: str | None = "approval-1"
    published_branch: str = BRANCH
    published_commit: str = COMMIT
    published_tree: str = TREE
    published_at: object | None = object()
    deployment_release_id: str | None = RELEASE_ID
    deployment_prior_release_id: str | None = PRIOR_RELEASE_ID
    deployed_at: object | None = object()
    rollback_release_id: str | None = None
    rolled_back_at: object | None = None


class MissionService:
    def __init__(self, repository="dripvid"):
        self.mission = Mission(objectives=[repository, "change it"])

    def get_mission(self, mission_id):
        assert mission_id == self.mission.id
        return self.mission


class DeliveryService:
    def __init__(self, *, decision="approved", qa_result=QAResult.PASSED):
        self.decision = decision
        self.delivery = Delivery(
            changed_files=["src/ai_hq/example.py"],
            developer_evidence={
                "verification": "candidate_identity_verified",
                "algorithm": "sha256",
                "change_ref": CHANGE_REF,
                "repository": "dripvid",
                "base_ref": "main",
                "base_commit": "d" * 40,
                "workspace_id": "11111111-1111-1111-1111-111111111111",
                "diff_digest": "sha256:" + "e" * 64,
                "content_digest": "sha256:" + "f" * 64,
            },
            qa_result=qa_result,
            qa_evidence={"qa": "passed"},
        )
        self.decision_calls = []
        self.rollback_calls = []

    def get_delivery(self, mission_id):
        assert mission_id == self.delivery.mission_id
        return self.delivery

    def apply_human_decision(self, *, mission_id, approval_reference, change_ref):
        self.decision_calls.append((mission_id, approval_reference, change_ref))
        if approval_reference != self.delivery.approval_reference:
            raise ValueError("approval reference does not match delivery")
        if change_ref != self.delivery.change_ref:
            raise ValueError("change_ref does not match approved proposal")
        if self.decision == "pending":
            raise ValueError("approval request has not been decided")
        if self.decision == "denied":
            self.delivery.stage = DeliveryStage.DEVELOPER
            self.delivery.approval_reference = None
        return self.delivery

    def record_rollback(self, **kwargs):
        self.rollback_calls.append(kwargs)
        self.delivery.rollback_release_id = kwargs["release_id"]
        self.delivery.rolled_back_at = object()
        return self.delivery


class Rollbacker:
    def __init__(self):
        self.calls = []

    def rollback(self, target, *, release_id):
        self.calls.append((target, release_id))
        return RolledBackRelease(
            repository=target.repository,
            change_ref=target.change_ref,
            release_id=release_id,
        )


def build(
    *,
    repository="dripvid",
    decision="approved",
    qa_result=QAResult.PASSED,
    with_rollbacker=True,
):
    missions = MissionService(repository)
    deliveries = DeliveryService(decision=decision, qa_result=qa_result)
    rollbacker = Rollbacker() if with_rollbacker else None
    service = CodeChangeService(
        mission_service=missions,
        delivery_service=deliveries,
        runner_factory=lambda repository: None,
        candidate_store=None,
        publisher=None,
        deployer=None,
        rollbacker=rollbacker,
    )
    return service, deliveries, rollbacker


def invoke(service, **overrides):
    values = {
        "mission_id": "mission-1",
        "approval_reference": "approval-1",
        "change_ref": CHANGE_REF,
    }
    values.update(overrides)
    return service.rollback_approved_deployment(**values)


def test_approved_prior_release_rolls_back_once_and_records_identity():
    service, deliveries, rollbacker = build()

    result = invoke(service)

    assert result.deployed is True
    assert result.rolled_back is True
    assert result.rollback_release_id == PRIOR_RELEASE_ID
    assert rollbacker.calls[0][1] == PRIOR_RELEASE_ID
    assert deliveries.rollback_calls == [
        {
            "mission_id": "mission-1",
            "change_ref": CHANGE_REF,
            "release_id": PRIOR_RELEASE_ID,
        }
    ]


def test_rollback_replay_returns_persisted_identity_without_remote_mutation():
    service, deliveries, rollbacker = build()

    invoke(service)
    deliveries.delivery.rollback_release_id = PRIOR_RELEASE_ID
    result = invoke(service)

    assert result.rolled_back is True
    assert result.rollback_release_id == PRIOR_RELEASE_ID
    assert len(rollbacker.calls) == 1
    assert len(deliveries.rollback_calls) == 1


def test_unconfigured_rollbacker_fails_closed():
    service, deliveries, rollbacker = build(with_rollbacker=False)

    with pytest.raises(RuntimeError, match="rollback"):
        invoke(service)

    assert rollbacker is None
    assert deliveries.rollback_calls == []


@pytest.mark.parametrize("decision", ["pending", "denied"])
def test_non_approved_human_decision_blocks_rollbacker(decision):
    service, deliveries, rollbacker = build(decision=decision)

    with pytest.raises(ValueError, match="approval|approved"):
        invoke(service)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_mismatched_approval_or_change_ref_blocks_before_rollbacker():
    service, deliveries, rollbacker = build()

    with pytest.raises(ValueError, match="approval"):
        invoke(service, approval_reference="wrong")
    with pytest.raises(ValueError, match="change_ref"):
        invoke(service, change_ref="sha256:" + "9" * 64)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_unpublished_candidate_blocks_rollbacker():
    service, deliveries, rollbacker = build()
    deliveries.delivery.published_branch = None

    with pytest.raises(ValueError, match="published"):
        invoke(service)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_undeployed_candidate_blocks_rollbacker():
    service, deliveries, rollbacker = build()
    deliveries.delivery.deployment_release_id = None
    deliveries.delivery.deployment_prior_release_id = None

    with pytest.raises(ValueError, match="deployed"):
        invoke(service)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_missing_prior_release_blocks_rollbacker():
    service, deliveries, rollbacker = build()
    deliveries.delivery.deployment_prior_release_id = None

    with pytest.raises(ValueError, match="prior known-good"):
        invoke(service)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_conflicting_persisted_rollback_blocks_before_rollbacker():
    service, deliveries, rollbacker = build()
    deliveries.delivery.rollback_release_id = "dripvid-2026-09-01.other"

    with pytest.raises(ValueError, match="rollback identity"):
        invoke(service)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_qa_failure_blocks_rollbacker():
    service, deliveries, rollbacker = build(qa_result=QAResult.FAILED)

    with pytest.raises(ValueError, match="QA|qa"):
        invoke(service)

    assert rollbacker.calls == []
    assert deliveries.rollback_calls == []


def test_unknown_repository_blocks_before_rollbacker():
    service, deliveries, rollbacker = build(repository="other")

    with pytest.raises(ValueError, match="trusted repository"):
        invoke(service)

    assert deliveries.decision_calls == []
    assert rollbacker.calls == []