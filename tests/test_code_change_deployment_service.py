from dataclasses import dataclass

import pytest

from ai_hq.code_changes.candidate_store import PersistedCandidate
from ai_hq.code_changes.deployer import DeployedRelease
from ai_hq.code_changes.service import CodeChangeService
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.missions.models import MissionStatus


CHANGE_REF = "sha256:" + "a" * 64
BRANCH = "ai-hq/candidate/111111111111-aaaaaaaaaaaa"
COMMIT = "b" * 40
TREE = "c" * 40
BASE = "d" * 40
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
    deployment_release_id: str | None = None
    deployment_prior_release_id: str | None = None
    deployed_at: object | None = None


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
        self.deployment_calls = []

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
        self.delivery.published_branch = kwargs["branch_name"]
        self.delivery.published_commit = kwargs["commit_sha"]
        self.delivery.published_tree = kwargs["tree_sha"]
        self.delivery.published_at = object()
        return self.delivery

    def record_deployment(self, **kwargs):
        self.deployment_calls.append(kwargs)
        self.delivery.deployment_release_id = kwargs["release_id"]
        self.delivery.deployment_prior_release_id = kwargs.get("prior_release_id")
        self.delivery.deployed_at = object()
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


class Deployer:
    def __init__(self):
        self.calls = []

    def deploy(self, published):
        self.calls.append(published)
        return DeployedRelease(
            repository=published.repository,
            change_ref=published.change_ref,
            release_id=RELEASE_ID,
            prior_release_id=PRIOR_RELEASE_ID,
        )


def build(
    *,
    repository="ai-hq",
    decision="approved",
    qa_result=QAResult.PASSED,
    with_deployer=True,
):
    missions = MissionService(repository)
    deliveries = DeliveryService(decision=decision, qa_result=qa_result)
    store = CandidateStore()
    publish_publisher = None
    deployer = Deployer() if with_deployer else None
    service = CodeChangeService(
        mission_service=missions,
        delivery_service=deliveries,
        runner_factory=lambda repository: None,
        candidate_store=store,
        publisher=publish_publisher,
        deployer=deployer,
    )
    return service, deliveries, store, deployer


def test_approved_published_exact_candidate_deploys_once_and_records_identity():
    service, deliveries, store, deployer = build()

    result = service.deploy_approved_candidate(
        mission_id="mission-1",
        approval_reference="approval-1",
        change_ref=CHANGE_REF,
    )

    assert result.published is True
    assert result.deployed is True
    assert result.deployment_release_id == RELEASE_ID
    assert result.deployment_prior_release_id == PRIOR_RELEASE_ID
    assert len(store.calls) == 1
    assert len(deployer.calls) == 1
    assert deliveries.deployment_calls == [
        {
            "mission_id": "mission-1",
            "change_ref": CHANGE_REF,
            "release_id": RELEASE_ID,
            "prior_release_id": PRIOR_RELEASE_ID,
        }
    ]


def test_deployment_replay_returns_persisted_identity_without_remote_mutation():
    service, deliveries, store, deployer = build()

    service.deploy_approved_candidate(
        mission_id="mission-1",
        approval_reference="approval-1",
        change_ref=CHANGE_REF,
    )
    deliveries.deployment_release_id = RELEASE_ID
    deliveries.deployment_prior_release_id = PRIOR_RELEASE_ID
    result = service.deploy_approved_candidate(
        mission_id="mission-1",
        approval_reference="approval-1",
        change_ref=CHANGE_REF,
    )

    assert result.deployed is True
    assert len(store.calls) == 1
    assert len(deployer.calls) == 1
    assert len(deliveries.deployment_calls) == 1


def test_unconfigured_deployer_fails_closed():
    service, deliveries, store, deployer = build(with_deployer=False)

    with pytest.raises(RuntimeError, match="deployment"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert store.calls == []
    assert deliveries.deployment_calls == []


@pytest.mark.parametrize("decision", ["pending", "denied"])
def test_non_approved_human_decision_blocks_deployer(decision):
    service, deliveries, store, deployer = build(decision=decision)

    with pytest.raises(ValueError, match="approval|approved"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert store.calls == []
    assert deployer.calls == []
    assert deliveries.deployment_calls == []


def test_mismatched_approval_or_change_ref_blocks_before_deployer():
    service, deliveries, store, deployer = build()

    with pytest.raises(ValueError, match="approval"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="wrong",
            change_ref=CHANGE_REF,
        )
    with pytest.raises(ValueError, match="change_ref"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref="sha256:" + "9" * 64,
        )

    assert store.calls == []
    assert deployer.calls == []
    assert deliveries.deployment_calls == []


def test_unpublished_candidate_blocks_deployer():
    service, deliveries, store, deployer = build()
    deliveries.delivery.published_branch = None

    with pytest.raises(ValueError, match="published"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert store.calls == []
    assert deployer.calls == []
    assert deliveries.deployment_calls == []


def test_qa_failure_blocks_deployer():
    service, deliveries, store, deployer = build(qa_result=QAResult.FAILED)

    with pytest.raises(ValueError, match="QA|qa"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert store.calls == []
    assert deployer.calls == []
    assert deliveries.deployment_calls == []


def test_unknown_repository_blocks_before_deployer():
    service, deliveries, store, deployer = build(repository="other")

    with pytest.raises(ValueError, match="trusted repository"):
        service.deploy_approved_candidate(
            mission_id="mission-1",
            approval_reference="approval-1",
            change_ref=CHANGE_REF,
        )

    assert deliveries.decision_calls == []
    assert store.calls == []
    assert deployer.calls == []