from dataclasses import dataclass

import pytest

from ai_hq.code_changes.service import (
    CodeChangeResult,
    CodeChangeService,
)
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.missions.models import MissionRisk


@dataclass
class FakeMission:
    id: str
    risk: MissionRisk = MissionRisk.AMBER


@dataclass
class FakeDelivery:
    mission_id: str
    change_ref: str
    summary: str
    changed_files: list[str]
    developer_evidence: dict
    qa_result: QAResult | None = None
    qa_evidence: dict | None = None
    stage: DeliveryStage = DeliveryStage.QA
    approval_reference: str | None = None


class FakeMissionService:
    def __init__(self):
        self.created = []

    def create_mission(self, **kwargs):
        self.created.append(kwargs)
        return FakeMission(id="mission-123")


class FakeDeliveryService:
    def __init__(self):
        self.delivery = FakeDelivery(
            mission_id="mission-123",
            change_ref="sha256:" + ("a" * 64),
            summary="Make the toolbar smaller",
            changed_files=["public/css/app.css"],
            developer_evidence={
                "verification": "candidate_identity_verified",
                "tests": {
                    "passed": True,
                    "exit_code": 0,
                },
            },
        )

    def get_delivery(self, mission_id):
        assert mission_id == "mission-123"
        return self.delivery


class FakeRunner:
    def __init__(self, delivery_service, *, qa_passes=True):
        self.delivery_service = delivery_service
        self.qa_passes = qa_passes
        self.developer_calls = []
        self.qa_calls = []

    def run_developer(self, *, mission_id):
        self.developer_calls.append(mission_id)
        return True

    def run_qa(self, delivery):
        self.qa_calls.append(delivery.change_ref)

        if self.qa_passes:
            delivery.qa_result = QAResult.PASSED
            delivery.qa_evidence = {
                "review": "exact candidate accepted",
            }
            delivery.stage = DeliveryStage.WAITING_APPROVAL
            delivery.approval_reference = "approval-123"
        else:
            delivery.qa_result = QAResult.FAILED
            delivery.qa_evidence = {
                "review": "candidate rejected",
            }
            delivery.stage = DeliveryStage.DEVELOPER

        return True


class FakeRunnerFactory:
    def __init__(self, delivery_service, *, qa_passes=True):
        self.delivery_service = delivery_service
        self.qa_passes = qa_passes
        self.repositories = []
        self.runners = []

    def __call__(self, repository):
        self.repositories.append(repository)
        runner = FakeRunner(
            self.delivery_service,
            qa_passes=self.qa_passes,
        )
        self.runners.append(runner)
        return runner


def build_service(*, qa_passes=True):
    mission_service = FakeMissionService()
    delivery_service = FakeDeliveryService()
    runner_factory = FakeRunnerFactory(
        delivery_service,
        qa_passes=qa_passes,
    )

    service = CodeChangeService(
        mission_service=mission_service,
        delivery_service=delivery_service,
        runner_factory=runner_factory,
    )

    return (
        service,
        mission_service,
        delivery_service,
        runner_factory,
    )


@pytest.mark.parametrize(
    "repository",
    [
        "ai-hq",
        "dripvid",
    ],
)
def test_code_change_service_accepts_only_trusted_repository(
    repository,
):
    (
        service,
        mission_service,
        _delivery_service,
        runner_factory,
    ) = build_service()

    result = service.prepare_candidate(
        repository=repository,
        instruction="Make the toolbar smaller",
    )

    assert isinstance(result, CodeChangeResult)
    assert result.repository == repository

    assert runner_factory.repositories == [repository]

    created = mission_service.created[0]

    assert created["source"] == "hq_chat_code_change"
    assert created["owner_agent"] == "developer"
    assert created["risk"] == MissionRisk.AMBER
    assert created["description"] == "Make the toolbar smaller"

    assert repository in created["objectives"]


def test_unknown_repository_fails_closed_before_mission_creation():
    (
        service,
        mission_service,
        _delivery_service,
        runner_factory,
    ) = build_service()

    with pytest.raises(
        ValueError,
        match="trusted repository",
    ):
        service.prepare_candidate(
            repository="evil/repository",
            instruction="change something",
        )

    assert mission_service.created == []
    assert runner_factory.repositories == []


def test_blank_instruction_fails_closed():
    (
        service,
        mission_service,
        _delivery_service,
        runner_factory,
    ) = build_service()

    with pytest.raises(
        ValueError,
        match="instruction",
    ):
        service.prepare_candidate(
            repository="dripvid",
            instruction="   ",
        )

    assert mission_service.created == []
    assert runner_factory.repositories == []


def test_developer_runs_before_qa():
    (
        service,
        _mission_service,
        _delivery_service,
        runner_factory,
    ) = build_service()

    result = service.prepare_candidate(
        repository="dripvid",
        instruction="Make the toolbar smaller",
    )

    runner = runner_factory.runners[0]

    assert runner.developer_calls == ["mission-123"]
    assert runner.qa_calls == [
        "sha256:" + ("a" * 64),
    ]

    assert result.qa_result == QAResult.PASSED
    assert result.ready_for_approval is True
    assert result.approval_reference == "approval-123"


def test_result_uses_machine_verified_candidate_identity():
    (
        service,
        _mission_service,
        _delivery_service,
        _runner_factory,
    ) = build_service()

    result = service.prepare_candidate(
        repository="dripvid",
        instruction="Make the toolbar smaller",
    )

    assert result.change_ref == "sha256:" + ("a" * 64)

    assert result.changed_files == (
        "public/css/app.css",
    )

    assert (
        result.developer_evidence["verification"]
        == "candidate_identity_verified"
    )

    assert result.developer_evidence["tests"]["passed"] is True


def test_failed_qa_is_not_ready_for_approval():
    (
        service,
        _mission_service,
        _delivery_service,
        _runner_factory,
    ) = build_service(qa_passes=False)

    result = service.prepare_candidate(
        repository="dripvid",
        instruction="Make the toolbar smaller",
    )

    assert result.qa_result == QAResult.FAILED
    assert result.ready_for_approval is False
    assert result.approval_reference is None


@pytest.mark.parametrize(
    "path",
    [
        "src/ai_hq/auth/session.py",
        "src/ai_hq/approvals/service.py",
        "src/ai_hq/tool_gateway/gateway.py",
        "src/ai_hq/host_helper/client.py",
        "src/ai_hq/delivery/repository_sandbox.py",
        "deploy/ai-hq-deploy",
    ],
)
def test_sensitive_ai_hq_changes_are_high_risk(path):
    (
        service,
        _mission_service,
        delivery_service,
        _runner_factory,
    ) = build_service()

    delivery_service.delivery.changed_files = [path]

    result = service.prepare_candidate(
        repository="ai-hq",
        instruction="Change an AI HQ internal",
    )

    assert result.high_risk is True


def test_normal_dripvid_ui_change_is_not_high_risk():
    (
        service,
        _mission_service,
        delivery_service,
        _runner_factory,
    ) = build_service()

    delivery_service.delivery.changed_files = [
        "public/css/app.css",
        "public/watch.html",
    ]

    result = service.prepare_candidate(
        repository="dripvid",
        instruction="Make the toolbar smaller",
    )

    assert result.high_risk is False


def test_phase_a_result_never_claims_deployment():
    (
        service,
        _mission_service,
        _delivery_service,
        _runner_factory,
    ) = build_service()

    result = service.prepare_candidate(
        repository="dripvid",
        instruction="Make the toolbar smaller",
    )

    assert result.deployed is False
    assert result.published is False
