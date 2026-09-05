import json

import pytest

from ai_hq.delivery.model_agents import (
    ModelBackedDeveloperAgent,
    ModelBackedQAAgent,
)
from ai_hq.delivery.models import QAResult


class FakeModelClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def reply(self, system_prompt, messages):
        self.calls.append({
            "system_prompt": system_prompt,
            "messages": messages,
        })
        return self.response


def test_developer_returns_strict_structured_candidate():
    client = FakeModelClient(json.dumps({
        "change_ref": "immutable-dev-abc123",
        "summary": "Implement delivery orchestration",
        "changed_files": [
            "src/ai_hq/delivery/example.py",
            "tests/test_delivery_example.py",
        ],
        "evidence": {
            "tests": "12 passed",
            "review": "implementation complete",
        },
    }))

    developer = ModelBackedDeveloperAgent(client)

    result = developer.execute(
        mission_id="mission-1",
    )

    assert result == {
        "change_ref": "immutable-dev-abc123",
        "summary": "Implement delivery orchestration",
        "changed_files": [
            "src/ai_hq/delivery/example.py",
            "tests/test_delivery_example.py",
        ],
        "evidence": {
            "tests": "12 passed",
            "review": "implementation complete",
        },
    }

    assert len(client.calls) == 1


def test_developer_prompt_requires_immutable_reference_and_evidence():
    client = FakeModelClient(json.dumps({
        "change_ref": "ref-1",
        "summary": "Candidate",
        "changed_files": [],
        "evidence": {
            "tests": "passed",
        },
    }))

    developer = ModelBackedDeveloperAgent(client)

    developer.execute(
        mission_id="mission-2",
    )

    prompt = client.calls[0]["system_prompt"].lower()

    assert "change_ref" in prompt
    assert "immutable" in prompt
    assert "evidence" in prompt
    assert "json" in prompt


def test_developer_rejects_missing_change_ref():
    client = FakeModelClient(json.dumps({
        "summary": "Candidate",
        "changed_files": [],
        "evidence": {
            "tests": "passed",
        },
    }))

    developer = ModelBackedDeveloperAgent(client)

    with pytest.raises(ValueError, match="change_ref"):
        developer.execute(
            mission_id="mission-3",
        )


def test_developer_rejects_missing_evidence():
    client = FakeModelClient(json.dumps({
        "change_ref": "ref-3",
        "summary": "Candidate",
        "changed_files": [],
        "evidence": {},
    }))

    developer = ModelBackedDeveloperAgent(client)

    with pytest.raises(ValueError, match="evidence"):
        developer.execute(
            mission_id="mission-3",
        )


def test_developer_rejects_non_json_model_output():
    client = FakeModelClient(
        "I finished the implementation."
    )

    developer = ModelBackedDeveloperAgent(client)

    with pytest.raises(ValueError, match="JSON"):
        developer.execute(
            mission_id="mission-4",
        )


def test_qa_receives_exact_change_reference():
    client = FakeModelClient(json.dumps({
        "result": "PASSED",
        "evidence": {
            "tests": "12 passed",
            "review": "exact candidate verified",
        },
    }))

    qa = ModelBackedQAAgent(client)

    result = qa.review(
        mission_id="mission-5",
        change_ref="immutable-exact-555",
        summary="Exact proposal",
        changed_files=["src/example.py"],
        developer_evidence={
            "tests": "12 passed",
        },
    )

    assert result == {
        "result": QAResult.PASSED,
        "evidence": {
            "tests": "12 passed",
            "review": "exact candidate verified",
        },
    }

    messages = client.calls[0]["messages"]
    serialized = json.dumps(messages)

    assert "immutable-exact-555" in serialized


def test_qa_can_fail_candidate():
    client = FakeModelClient(json.dumps({
        "result": "FAILED",
        "evidence": {
            "tests": "1 failed",
            "review": "regression detected",
        },
    }))

    qa = ModelBackedQAAgent(client)

    result = qa.review(
        mission_id="mission-6",
        change_ref="immutable-failed-666",
        summary="Candidate",
        changed_files=["src/example.py"],
        developer_evidence={
            "tests": "developer tests passed",
        },
    )

    assert result["result"] is QAResult.FAILED
    assert result["evidence"]["tests"] == "1 failed"


def test_qa_rejects_invalid_result():
    client = FakeModelClient(json.dumps({
        "result": "MAYBE",
        "evidence": {
            "review": "uncertain",
        },
    }))

    qa = ModelBackedQAAgent(client)

    with pytest.raises(
        ValueError,
        match="PASSED or FAILED",
    ):
        qa.review(
            mission_id="mission-7",
            change_ref="ref-7",
            summary="Candidate",
            changed_files=[],
            developer_evidence={
                "tests": "passed",
            },
        )


def test_qa_rejects_missing_evidence():
    client = FakeModelClient(json.dumps({
        "result": "PASSED",
        "evidence": {},
    }))

    qa = ModelBackedQAAgent(client)

    with pytest.raises(ValueError, match="evidence"):
        qa.review(
            mission_id="mission-8",
            change_ref="ref-8",
            summary="Candidate",
            changed_files=[],
            developer_evidence={
                "tests": "passed",
            },
        )


def test_qa_rejects_non_json_model_output():
    client = FakeModelClient(
        "Everything looks good."
    )

    qa = ModelBackedQAAgent(client)

    with pytest.raises(ValueError, match="JSON"):
        qa.review(
            mission_id="mission-9",
            change_ref="ref-9",
            summary="Candidate",
            changed_files=[],
            developer_evidence={
                "tests": "passed",
            },
        )


def test_model_agents_do_not_receive_deployment_authority():
    import inspect

    import ai_hq.delivery.model_agents as module

    source = inspect.getsource(module)

    prohibited = (
        "subprocess.run(",
        "subprocess.Popen(",
        "os.system(",
        ".deploy(",
        ".rollback(",
        ".restart(",
        "HostHelperClient(",
        "ToolGateway(",
    )

    for token in prohibited:
        assert token not in source
