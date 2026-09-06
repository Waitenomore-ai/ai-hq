from dataclasses import dataclass

import pytest

from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.delivery.repository_workspace import (
    CandidateSnapshot,
    RepositoryWorkspace,
)
from ai_hq.delivery.repository_workspace import (
    TestEvidence as WorkspaceTestEvidence,
)


@dataclass
class FakeDelivery:
    mission_id: str
    stage: DeliveryStage
    change_ref: str = ""
    summary: str = ""
    changed_files: list | None = None
    developer_evidence: dict | None = None


class FakeDeliveryRuntime:
    def __init__(self):
        self.developer_calls = []
        self.qa_calls = []

    def handoff_to_developer(
        self,
        *,
        mission_id,
        change_ref,
        summary,
        changed_files,
        evidence,
    ):
        self.developer_calls.append(
            {
                "mission_id": mission_id,
                "change_ref": change_ref,
                "summary": summary,
                "changed_files": changed_files,
                "evidence": evidence,
            }
        )
        return FakeDelivery(
            mission_id=mission_id,
            stage=DeliveryStage.QA,
            change_ref=change_ref,
            summary=summary,
            changed_files=changed_files,
            developer_evidence=evidence,
        )

    def handoff_to_qa(
        self,
        *,
        mission_id,
        change_ref,
        result,
        evidence,
    ):
        self.qa_calls.append(
            {
                "mission_id": mission_id,
                "change_ref": change_ref,
                "result": result,
                "evidence": evidence,
            }
        )


class FakeDeveloper:
    def __init__(self, candidate):
        self.candidate = candidate
        self.calls = []

    def execute(self, *, mission_id):
        self.calls.append(mission_id)
        return self.candidate


class FakeQA:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def review(
        self,
        *,
        mission_id,
        change_ref,
        summary,
        changed_files,
        developer_evidence,
    ):
        self.calls.append(
            {
                "mission_id": mission_id,
                "change_ref": change_ref,
                "summary": summary,
                "changed_files": changed_files,
                "developer_evidence": developer_evidence,
            }
        )
        return self.result


class FakeWorkspaceService:
    def __init__(self, *, fail_at=None, tests_passed=True):
        self.fail_at = fail_at
        self.calls = []
        self.tests_passed = tests_passed
        self.workspace = RepositoryWorkspace(
            mission_id="mission-1",
            repository="Waitenomore-ai/ai-hq",
            base_ref="abc123",
            workspace_id="workspace-1",
        )

    def prepare(self, *, mission_id):
        self.calls.append(("prepare", mission_id))
        if self.fail_at == "prepare":
            raise RuntimeError("prepare failed")
        return RepositoryWorkspace(
            mission_id=mission_id,
            repository=self.workspace.repository,
            base_ref=self.workspace.base_ref,
            workspace_id=self.workspace.workspace_id,
        )

    def snapshot(self, *, workspace):
        self.calls.append(("snapshot", workspace.workspace_id))
        if self.fail_at == "snapshot":
            raise RuntimeError("snapshot failed")
        return CandidateSnapshot(
            workspace_id=workspace.workspace_id,
            repository=workspace.repository,
            base_ref=workspace.base_ref,
            changed_files=("src/real.py", "tests/test_real.py"),
            diff_digest="sha256:" + ("a" * 64),
            content_digest="sha256:" + ("b" * 64),
        )

    def run_tests(self, *, workspace):
        self.calls.append(("run_tests", workspace.workspace_id))
        if self.fail_at == "run_tests":
            raise RuntimeError("tests failed to execute")
        return WorkspaceTestEvidence(
            passed=self.tests_passed,
            exit_code=0 if self.tests_passed else 1,
            summary="42 passed" if self.tests_passed else "1 failed",
            evidence_digest="sha256:" + ("c" * 64),
        )


def developer_candidate():
    return {
        "change_ref": "MODEL-INVENTED-REF",
        "summary": "Developer implementation candidate",
        "changed_files": ["model/claimed.py"],
        "evidence": {"source": "developer", "tests": "claimed pass"},
    }


def qa_pass():
    return {
        "result": QAResult.PASSED,
        "evidence": {"review": "approved by QA"},
    }


def qa_fail():
    return {
        "result": QAResult.FAILED,
        "evidence": {"review": "returned to Developer"},
    }


def developer_runner(*, workspace_service=None):
    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(developer_candidate())
    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=FakeQA(qa_pass()),
        candidate_verifier=CandidateVerifier(),
        workspace_service=workspace_service or FakeWorkspaceService(),
    )
    return runner, runtime, developer


def test_developer_stage_uses_workspace_machine_state_for_persistence():
    workspace_service = FakeWorkspaceService()
    runner, runtime, developer = developer_runner(
        workspace_service=workspace_service
    )

    assert runner.run_developer(mission_id="mission-1") is True
    assert developer.calls == ["mission-1"]
    assert workspace_service.calls == [
        ("prepare", "mission-1"),
        ("snapshot", "workspace-1"),
        ("run_tests", "workspace-1"),
    ]

    call = runtime.developer_calls[0]
    assert call["change_ref"].startswith("sha256:")
    assert call["change_ref"] != "MODEL-INVENTED-REF"
    assert call["changed_files"] == ["src/real.py", "tests/test_real.py"]
    assert "model/claimed.py" not in call["changed_files"]
    assert call["evidence"]["tests"] == {
        "passed": True,
        "exit_code": 0,
        "summary": "42 passed",
        "evidence_digest": "sha256:" + ("c" * 64),
    }
    assert "source" not in call["evidence"]


def test_failed_machine_tests_fail_closed_before_runtime_handoff():
    workspace_service = FakeWorkspaceService(tests_passed=False)
    runner, runtime, _ = developer_runner(workspace_service=workspace_service)

    with pytest.raises(ValueError, match="workspace tests must pass"):
        runner.run_developer(mission_id="mission-1")

    assert runtime.developer_calls == []


@pytest.mark.parametrize("fail_at", ["prepare", "snapshot", "run_tests"])
def test_workspace_failures_fail_closed_before_runtime_handoff(fail_at):
    workspace_service = FakeWorkspaceService(fail_at=fail_at)
    runner, runtime, _ = developer_runner(workspace_service=workspace_service)

    with pytest.raises(RuntimeError):
        runner.run_developer(mission_id="mission-1")

    assert runtime.developer_calls == []


def test_developer_stage_requires_workspace_service_and_verifier():
    runtime = FakeDeliveryRuntime()

    missing_workspace = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(developer_candidate()),
        qa=FakeQA(qa_pass()),
        candidate_verifier=CandidateVerifier(),
    )
    with pytest.raises(ValueError, match="workspace service"):
        missing_workspace.run_developer(mission_id="mission-1")

    missing_verifier = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(developer_candidate()),
        qa=FakeQA(qa_pass()),
        workspace_service=FakeWorkspaceService(),
    )
    with pytest.raises(ValueError, match="candidate verifier"):
        missing_verifier.run_developer(mission_id="mission-1")

    assert runtime.developer_calls == []


def test_qa_reviews_exact_persisted_developer_change():
    runtime = FakeDeliveryRuntime()
    qa = FakeQA(qa_pass())
    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(developer_candidate()),
        qa=qa,
    )
    delivery = FakeDelivery(
        mission_id="mission-2",
        stage=DeliveryStage.QA,
        change_ref="exact-ref-456",
        summary="Exact persisted proposal",
        changed_files=["src/example.py"],
        developer_evidence={"verification": "candidate_identity_verified"},
    )

    assert runner.run_qa(delivery) is True
    assert qa.calls[0]["change_ref"] == "exact-ref-456"
    assert runtime.qa_calls[0]["change_ref"] == "exact-ref-456"
    assert runtime.qa_calls[0]["result"] is QAResult.PASSED


def test_qa_failure_is_recorded_against_exact_change():
    runtime = FakeDeliveryRuntime()
    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(developer_candidate()),
        qa=FakeQA(qa_fail()),
    )
    delivery = FakeDelivery(
        mission_id="mission-3",
        stage=DeliveryStage.QA,
        change_ref="failed-ref-789",
        summary="Candidate needing revision",
        changed_files=["src/failing.py"],
        developer_evidence={"verification": "candidate_identity_verified"},
    )

    runner.run_qa(delivery)

    assert runtime.qa_calls[0]["change_ref"] == "failed-ref-789"
    assert runtime.qa_calls[0]["result"] is QAResult.FAILED


def test_qa_result_requires_evidence():
    runtime = FakeDeliveryRuntime()
    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(developer_candidate()),
        qa=FakeQA({"result": QAResult.PASSED, "evidence": {}}),
    )
    delivery = FakeDelivery(
        mission_id="mission-5",
        stage=DeliveryStage.QA,
        change_ref="exact-ref",
        summary="Proposal",
        changed_files=[],
        developer_evidence={"verification": "candidate_identity_verified"},
    )

    with pytest.raises(ValueError, match="evidence"):
        runner.run_qa(delivery)

    assert runtime.qa_calls == []


def test_agent_runner_has_no_direct_production_execution_capability():
    import inspect

    import ai_hq.delivery.agent_runner as module

    source = inspect.getsource(module)
    prohibited = (
        "subprocess.run(",
        "subprocess.Popen(",
        "os.system(",
        ".deploy(",
        ".rollback(",
        ".restart(",
        "ai_hq.host_helper",
        "ToolGateway(",
    )

    for token in prohibited:
        assert token not in source
