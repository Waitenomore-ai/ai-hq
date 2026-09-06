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


def developer_payload(*, changes=None, **extra):
    payload = {
        "summary": "Implement delivery orchestration",
        "changes": changes if changes is not None else [
            {
                "path": "src/ai_hq/delivery/example.py",
                "operation": "write",
                "content": "VALUE = 1\n",
            },
            {
                "path": "src/ai_hq/delivery/obsolete.py",
                "operation": "delete",
                "content": None,
            },
        ],
    }
    payload.update(extra)
    return payload


def test_developer_returns_strict_structured_file_changes():
    client = FakeModelClient(json.dumps(developer_payload()))
    developer = ModelBackedDeveloperAgent(client)

    result = developer.execute(mission_id="mission-1")

    assert result == developer_payload()
    assert len(client.calls) == 1


def test_developer_prompt_requires_typed_changes_and_forbids_command_authority():
    client = FakeModelClient(json.dumps(developer_payload()))
    developer = ModelBackedDeveloperAgent(client)

    developer.execute(mission_id="mission-2")

    prompt = client.calls[0]["system_prompt"].lower()
    assert "changes" in prompt
    assert "write" in prompt
    assert "delete" in prompt
    assert "shell" in prompt
    assert "deployment" in prompt
    assert "push" in prompt
    assert "merge" in prompt


def test_developer_rejects_missing_summary():
    payload = developer_payload()
    payload.pop("summary")
    developer = ModelBackedDeveloperAgent(FakeModelClient(json.dumps(payload)))

    with pytest.raises(ValueError, match="summary"):
        developer.execute(mission_id="mission-3")


def test_developer_rejects_non_list_changes():
    developer = ModelBackedDeveloperAgent(
        FakeModelClient(json.dumps(developer_payload(changes={})))
    )

    with pytest.raises(ValueError, match="changes"):
        developer.execute(mission_id="mission-4")


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "write", "content": "x\n"},
        {"path": "src/a.py", "operation": "rename", "content": "x\n"},
        {"path": "src/a.py", "operation": "write", "content": None},
        {"path": "src/a.py", "operation": "delete", "content": "x\n"},
        {"path": "src/a.py", "operation": "delete"},
    ],
)
def test_developer_rejects_invalid_change_shapes(change):
    developer = ModelBackedDeveloperAgent(
        FakeModelClient(json.dumps(developer_payload(changes=[change])))
    )

    expected = "content" if change.get("operation") == "delete" and "content" not in change else "change"
    with pytest.raises(ValueError, match=expected):
        developer.execute(mission_id="mission-5")


@pytest.mark.parametrize("field", ["command", "argv", "shell"])
def test_developer_rejects_command_control_fields(field):
    developer = ModelBackedDeveloperAgent(
        FakeModelClient(json.dumps(developer_payload(**{field: "blocked"})))
    )

    with pytest.raises(ValueError, match="command|authority|field"):
        developer.execute(mission_id="mission-6")


def test_developer_rejects_non_json_model_output():
    developer = ModelBackedDeveloperAgent(FakeModelClient("I finished the implementation."))

    with pytest.raises(ValueError, match="JSON"):
        developer.execute(mission_id="mission-7")


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
        mission_id="mission-8",
        change_ref="immutable-exact-555",
        summary="Exact proposal",
        changed_files=["src/example.py"],
        developer_evidence={"tests": "12 passed"},
    )

    assert result == {
        "result": QAResult.PASSED,
        "evidence": {
            "tests": "12 passed",
            "review": "exact candidate verified",
        },
    }
    assert "immutable-exact-555" in json.dumps(client.calls[0]["messages"])


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
        mission_id="mission-9",
        change_ref="immutable-failed-666",
        summary="Candidate",
        changed_files=["src/example.py"],
        developer_evidence={"tests": "developer tests passed"},
    )

    assert result["result"] is QAResult.FAILED
    assert result["evidence"]["tests"] == "1 failed"


def test_qa_rejects_invalid_result():
    qa = ModelBackedQAAgent(FakeModelClient(json.dumps({
        "result": "MAYBE",
        "evidence": {"review": "uncertain"},
    })))

    with pytest.raises(ValueError, match="PASSED or FAILED"):
        qa.review(
            mission_id="mission-10",
            change_ref="ref-10",
            summary="Candidate",
            changed_files=[],
            developer_evidence={"tests": "passed"},
        )


def test_qa_rejects_missing_evidence():
    qa = ModelBackedQAAgent(FakeModelClient(json.dumps({
        "result": "PASSED",
        "evidence": {},
    })))

    with pytest.raises(ValueError, match="evidence"):
        qa.review(
            mission_id="mission-11",
            change_ref="ref-11",
            summary="Candidate",
            changed_files=[],
            developer_evidence={"tests": "passed"},
        )


def test_qa_rejects_non_json_model_output():
    qa = ModelBackedQAAgent(FakeModelClient("Everything looks good."))

    with pytest.raises(ValueError, match="JSON"):
        qa.review(
            mission_id="mission-12",
            change_ref="ref-12",
            summary="Candidate",
            changed_files=[],
            developer_evidence={"tests": "passed"},
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
