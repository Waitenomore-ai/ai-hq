from dataclasses import dataclass

import pytest

from ai_hq.code_changes.candidate_store import PersistedCandidate
from ai_hq.code_changes.publisher import PublishedCandidate
from ai_hq.code_changes.service import CodeChangeService
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.missions.models import MissionStatus


CHANGE_REF = "sha256:" + "a" * 64
BRANCH = "ai-hq/candidate/111111111111-aaaaaaaaaaaa"
COMMIT = "b" * 40
TREE = "c" * 40
BASE = "d" * 40


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
    published_branch: str | None = None
    published_commit: str | None = None
    published_tree: str | None = None
    published_at: object | None = None


class MissionService:
    def __init__(self, repository="ai-hq"):
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
                "repository": "ai-hq",
                "base_ref": "main",
                "base_commit": BASE,
                "workspace_id": "11111111-1111-1111-1111-111111111111",
                "diff_digest": "sha256:" + "e" * 64,
                "content_digest": "sha256:" + "f" * 64,
            },
            qa_result=qa_result,
            qa_evidence={"qa": "passed"},
        )
        self.decision_calls = []
        self.publication_calls = []

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

    def record_publication(self, **kwargs):
        self.publication_calls.append(kwargs)
        self.delivery.published_branch = kwargs["branch_name"]
        self.delivery.published_commit = kwargs["commit_sha"]
        self.delivery.published_tree = kwargs["tree_sha"]
        self.delivery.published_at = object()
        return self.delivery


class CandidateStore:
    def __init__(self):
        self.calls = []

    def load_verified(self, **kwargs):
        self.calls.append(kwargs)
        return PersistedCandidate(
            mission_id=kwargs["mission_id"],
            repository=kwargs["evidence"]["repository"],
            workspace_id=kwargs["evidence"]["workspace_id"],
            base_ref="main",
            base_commit=BASE,
            change_ref=kwargs["change_ref"],
            changed_files=tuple(kwargs["changed_files"]),
            content_digest=kwargs["evidence"]["content_digest"],
            workspace_path=__import__("pathlib").Path("/trusted/candidate"),
        )


class Publisher:
    def __init__(self):
        self.calls = []

    def publish(self, candidate):
        self.calls.append(candidate)
        return PublishedCandidate(
            repository=candidate.repository,
            change_ref=candidate.change_ref,
            branch_name=BRANCH,
            commit_sha=COMMIT,
            tree_sha=TREE,
            base_commit=BASE,
        )


def build(*, repository="ai-hq", decision="approved", qa_result=QAResult.PASSED):
    missions = MissionService(repository)
    deliveries = DeliveryService(decision=decision, qa_result=qa_result)
    store = CandidateStore()
    publisher = Publisher()
    service = CodeChangeService(
        mission_service=missions,
        delivery_service=deliveries,
        runner_factory=lambda repository: None,
        candidate_store=store,
        publisher=publisher,
    )
    return service, deliveries, store, publisher


def test_approved_exact_candidate_publishes_once_and_records_identity():
    service, deliveries, store, publisher = build()

    result = service.publish_approved_candidate(
        mission_id="mission-1",
        approval_reference="approval-1",
        change_ref=CHANGE_REF,
    )

    assert result.published is True
    assert result.deployed is False
    assert len(store.calls) == 1
    assert len(publisher.calls) == 1
    assert deliveries.publication_calls == [
        {
            "mission_id": "mission-1",
            "change_ref": CHANGE_REF,
            "branch_name": BRANCH,
            "commit_sha": COMMIT,
            "tree_sha": TREE,
        }
    ]


def test_publication_replay_returns_persisted_identity_without_remote_mutation():
    service, deliveries, store, publisher = build()

    service.publish_approved_candidate(
        mission_id="mission-1",
        approval_reference="approval-1",
        change_ref=CHANGE_REF,
    )
    result = service.publish_approved_candidate(
        mission_id="mission-1",
        approval_reference="approval-1",
        change_ref=CHANGE_REF,
    )

    assert result.published is True
    assert len(store.calls) == 1
    assert len(publisher.calls) == 1
    assert len(deliveries.publication_calls) == 1


@pytest.mark.parametrize("decision", ["pending", "denied"])
def test_non_approved_human_decision_blocks_publisher(decision):
    service, deliveries, store, publisher = build(decision=decision)

    with pytest.raises(ValueError, match="approval|approved"):
        service.publish_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert store.calls == []
    assert publisher.calls == []
    assert deliveries.publication_calls == []


def test_mismatched_approval_or_change_ref_blocks_before_publisher():
    service, deliveries, store, publisher = build()

    with pytest.raises(ValueError, match="approval"):
        service.publish_approved_candidate(
            mission_id="mission-1",
            approval_reference="wrong",
            change_ref=CHANGE_REF,
        )
    with pytest.raises(ValueError, match="change_ref"):
        service.publish_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref="sha256:" + "9" * 64,
        )

    assert store.calls == []
    assert publisher.calls == []
    assert deliveries.publication_calls == []


def test_qa_failure_blocks_publisher():
    service, deliveries, store, publisher = build(qa_result=QAResult.FAILED)

    with pytest.raises(ValueError, match="QA|qa"):
        service.publish_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert store.calls == []
    assert publisher.calls == []
    assert deliveries.publication_calls == []


def test_unknown_repository_blocks_before_publisher():
    service, deliveries, store, publisher = build(repository="other")

    with pytest.raises(ValueError, match="trusted repository"):
        service.publish_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert deliveries.decision_calls == []
    assert store.calls == []
    assert publisher.calls == []
