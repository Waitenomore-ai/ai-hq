from dataclasses import dataclass

import pytest

from ai_hq.delivery.models import DeliveryStage, QAResult
from ai_hq.delivery.agent_runner import DeliveryAgentRunner
from ai_hq.delivery.candidate_verifier import CandidateVerifier


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
        self.developer_calls.append({
            "mission_id": mission_id,
            "change_ref": change_ref,
            "summary": summary,
            "changed_files": changed_files,
            "evidence": evidence,
        })

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
        self.qa_calls.append({
            "mission_id": mission_id,
            "change_ref": change_ref,
            "result": result,
            "evidence": evidence,
        })


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
        self.calls.append({
            "mission_id": mission_id,
            "change_ref": change_ref,
            "summary": summary,
            "changed_files": changed_files,
            "developer_evidence": developer_evidence,
        })

        return self.result


def developer_candidate(change_ref="immutable-abc123"):
    return {
        "change_ref": change_ref,
        "summary": "Developer implementation candidate",
        "changed_files": [
            "src/ai_hq/example.py",
            "tests/test_example.py",
        ],
        "evidence": {
            "tests": "42 passed",
            "source": "developer",
        },
    }


def qa_pass():
    return {
        "result": QAResult.PASSED,
        "evidence": {
            "tests": "42 passed",
            "review": "approved by QA",
        },
    }


def qa_fail():
    return {
        "result": QAResult.FAILED,
        "evidence": {
            "tests": "1 failed",
            "review": "returned to Developer",
        },
    }


def test_developer_stage_executes_developer_and_persists_candidate():
    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(developer_candidate())
    qa = FakeQA(qa_pass())

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
        candidate_verifier=CandidateVerifier(),
    )

    worked = runner.run_developer(
        mission_id="mission-1",
    )

    assert worked is True
    assert developer.calls == ["mission-1"]
    assert len(runtime.developer_calls) == 1

    call = runtime.developer_calls[0]

    assert call["mission_id"] == "mission-1"

    # The model-supplied reference must never cross
    # the trusted runtime boundary.
    assert call["change_ref"] != "immutable-abc123"
    assert call["change_ref"].startswith("sha256:")

    assert call["summary"] == (
        "Developer implementation candidate"
    )

    assert call["changed_files"] == [
        "src/ai_hq/example.py",
        "tests/test_example.py",
    ]

    # Only machine-generated verifier evidence is trusted.
    assert call["evidence"] == {
        "verification": "candidate_identity_verified",
        "algorithm": "sha256",
        "change_ref": call["change_ref"],
    }

    assert "tests" not in call["evidence"]
    assert "source" not in call["evidence"]

    assert qa.calls == []

def test_qa_reviews_exact_persisted_developer_change():
    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(developer_candidate())
    qa = FakeQA(qa_pass())

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
    )

    delivery = FakeDelivery(
        mission_id="mission-2",
        stage=DeliveryStage.QA,
        change_ref="exact-ref-456",
        summary="Exact persisted proposal",
        changed_files=["src/example.py"],
        developer_evidence={
            "tests": "99 passed",
        },
    )

    worked = runner.run_qa(delivery)

    assert worked is True

    assert qa.calls == [{
        "mission_id": "mission-2",
        "change_ref": "exact-ref-456",
        "summary": "Exact persisted proposal",
        "changed_files": ["src/example.py"],
        "developer_evidence": {
            "tests": "99 passed",
        },
    }]

    assert runtime.qa_calls == [{
        "mission_id": "mission-2",
        "change_ref": "exact-ref-456",
        "result": QAResult.PASSED,
        "evidence": {
            "tests": "42 passed",
            "review": "approved by QA",
        },
    }]


def test_qa_failure_is_recorded_against_exact_change():
    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(developer_candidate())
    qa = FakeQA(qa_fail())

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
    )

    delivery = FakeDelivery(
        mission_id="mission-3",
        stage=DeliveryStage.QA,
        change_ref="failed-ref-789",
        summary="Candidate needing revision",
        changed_files=["src/failing.py"],
        developer_evidence={
            "tests": "developer tests passed",
        },
    )

    runner.run_qa(delivery)

    assert runtime.qa_calls[0]["change_ref"] == "failed-ref-789"
    assert runtime.qa_calls[0]["result"] is QAResult.FAILED


def test_developer_candidate_requires_immutable_change_ref():
    runtime = FakeDeliveryRuntime()

    candidate = developer_candidate()
    candidate["change_ref"] = ""

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(candidate),
        qa=FakeQA(qa_pass()),
    )

    with pytest.raises(ValueError, match="change_ref"):
        runner.run_developer(
            mission_id="mission-4",
        )

    assert runtime.developer_calls == []


def test_qa_result_requires_evidence():
    runtime = FakeDeliveryRuntime()

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=FakeDeveloper(developer_candidate()),
        qa=FakeQA({
            "result": QAResult.PASSED,
            "evidence": {},
        }),
    )

    delivery = FakeDelivery(
        mission_id="mission-5",
        stage=DeliveryStage.QA,
        change_ref="exact-ref",
        summary="Proposal",
        changed_files=[],
        developer_evidence={
            "tests": "passed",
        },
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
    )

    for token in prohibited:
        assert token not in source


def test_developer_runner_replaces_model_change_ref_with_verified_ref():

    candidate = {
        "change_ref": "MODEL-INVENTED-REF",
        "summary": "Verified candidate",
        "changed_files": ["src/example.py"],
        "evidence": {
            "model_claim": "tests passed",
        },
    }

    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(candidate)
    qa = FakeQA({
        "result": QAResult.PASSED,
        "evidence": {"review": "ok"},
    })

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
        candidate_verifier=CandidateVerifier(),
    )

    runner.run_developer(
        mission_id="mission-verified-1",
    )

    assert len(runtime.developer_calls) == 1

    call = runtime.developer_calls[0]

    assert call["change_ref"] != "MODEL-INVENTED-REF"
    assert call["change_ref"].startswith("sha256:")


def test_developer_runner_uses_machine_verified_evidence_only():

    candidate = {
        "change_ref": "MODEL-REF",
        "summary": "Verified evidence",
        "changed_files": ["src/example.py"],
        "evidence": {
            "model_claim": "999 tests passed",
            "trusted": True,
        },
    }

    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(candidate)
    qa = FakeQA({
        "result": QAResult.PASSED,
        "evidence": {"review": "ok"},
    })

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
        candidate_verifier=CandidateVerifier(),
    )

    runner.run_developer(
        mission_id="mission-verified-2",
    )

    call = runtime.developer_calls[0]
    evidence = call["evidence"]

    assert evidence["verification"] == (
        "candidate_identity_verified"
    )

    assert evidence["change_ref"] == call["change_ref"]

    assert "model_claim" not in evidence
    assert "trusted" not in evidence


def test_developer_runner_preserves_verified_candidate_contents():

    candidate = {
        "change_ref": "MODEL-REF",
        "summary": "Exact verified summary",
        "changed_files": [
            "src/one.py",
            "tests/test_one.py",
        ],
        "evidence": {
            "model_claim": "ignored",
        },
    }

    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(candidate)
    qa = FakeQA({
        "result": QAResult.PASSED,
        "evidence": {"review": "ok"},
    })

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
        candidate_verifier=CandidateVerifier(),
    )

    runner.run_developer(
        mission_id="mission-verified-3",
    )

    call = runtime.developer_calls[0]

    assert call["summary"] == (
        "Exact verified summary"
    )

    assert call["changed_files"] == [
        "src/one.py",
        "tests/test_one.py",
    ]


def test_runner_without_verifier_fails_closed():
    candidate = {
        "change_ref": "MODEL-REF-MUST-NOT-CROSS",
        "summary": "Unsafe candidate",
        "changed_files": [],
        "evidence": {
            "model_claim": "passed",
        },
    }

    runtime = FakeDeliveryRuntime()
    developer = FakeDeveloper(candidate)
    qa = FakeQA({
        "result": QAResult.PASSED,
        "evidence": {"review": "ok"},
    })

    runner = DeliveryAgentRunner(
        runtime=runtime,
        developer=developer,
        qa=qa,
    )

    with pytest.raises(
        ValueError,
        match="verifier",
    ):
        runner.run_developer(
            mission_id="mission-no-verifier",
        )

    assert runtime.developer_calls == []
