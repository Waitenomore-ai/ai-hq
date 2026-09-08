import json

import pytest

from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent


class StaticModelClient:
    def __init__(self, response: str):
        self.response = response

    def reply(self, _system_prompt, _messages):
        return self.response


class ScriptedModelClient:
    """Returns scripted responses in order, repeating the last one."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = []

    def reply(self, system_prompt, messages):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
            }
        )

        if len(self.responses) > 1:
            return self.responses.pop(0)

        return self.responses[0]


def _context(_mission_id):
    return {
        "repository": "dripvid",
        "instruction": "Make the mobile menu smaller",
        "files": [
            {
                "path": "public/css/mobile-member.css",
                "content": ".menu { gap: 12px; }\n",
                "complete": True,
            }
        ],
    }


def _candidate_json():
    return json.dumps(
        {
            "summary": "Reduce mobile menu spacing",
            "changes": [
                {
                    "path": "public/css/mobile-member.css",
                    "operation": "write",
                    "content": ".menu { gap: 10px; }\n",
                }
            ],
        }
    )


def test_developer_accepts_single_json_markdown_fence():
    model = StaticModelClient(f"```json\n{_candidate_json()}\n```")
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    candidate = agent.execute(mission_id="mission-1")

    assert candidate["summary"] == "Reduce mobile menu spacing"
    assert candidate["changes"][0]["path"] == "public/css/mobile-member.css"


def test_developer_rejects_prose_wrapped_json():
    model = StaticModelClient(f"Here is the JSON:\n{_candidate_json()}")
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    with pytest.raises(ValueError, match="Developer must return valid JSON"):
        agent.execute(mission_id="mission-1")


def test_developer_rejects_prose_around_fenced_json():
    fenced = f"```json\n{_candidate_json()}\n```"
    model = ScriptedModelClient(
        [
            f"Here is the JSON:\n{fenced}",
            f"Here is the JSON:\n{fenced}",
        ]
    )
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    with pytest.raises(ValueError, match="Developer must return valid JSON"):
        agent.execute(mission_id="mission-1")

    assert len(model.calls) == 2


def test_developer_retries_once_and_accepts_valid_retry():
    model = ScriptedModelClient(
        [
            "I finished the implementation.",
            _candidate_json(),
        ]
    )
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    candidate = agent.execute(mission_id="mission-1")

    assert candidate["summary"] == "Reduce mobile menu spacing"
    assert candidate["changes"][0]["path"] == "public/css/mobile-member.css"
    assert len(model.calls) == 2


def test_developer_accepts_fenced_json_on_retry():
    model = ScriptedModelClient(
        [
            "I finished the implementation.",
            f"```json\n{_candidate_json()}\n```",
        ]
    )
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    candidate = agent.execute(mission_id="mission-1")

    assert candidate["summary"] == "Reduce mobile menu spacing"
    assert len(model.calls) == 2


def test_developer_retry_prompt_does_not_echo_invalid_response():
    invalid = "I finished the implementation."
    model = ScriptedModelClient([invalid, _candidate_json()])
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    agent.execute(mission_id="mission-1")

    retry_messages = model.calls[1]["messages"]

    assert invalid not in json.dumps(retry_messages)
    assert retry_messages[-1]["role"] == "user"
    assert "JSON" in retry_messages[-1]["content"]


def test_developer_fails_safely_after_second_invalid_response():
    model = ScriptedModelClient(
        [
            "I finished the implementation.",
            "The change reduces the mobile menu spacing.",
        ]
    )
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    with pytest.raises(ValueError, match="Developer must return valid JSON"):
        agent.execute(mission_id="mission-1")

    assert len(model.calls) == 2


def test_developer_valid_json_is_not_retried():
    model = ScriptedModelClient([_candidate_json()])
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    agent.execute(mission_id="mission-1")

    assert len(model.calls) == 1


def test_developer_schema_violation_fails_without_retry():
    payload = json.loads(_candidate_json())
    payload["command"] = "restart dripvid"
    model = ScriptedModelClient([json.dumps(payload)])
    agent = ModelBackedDeveloperAgent(model, context_provider=_context)

    with pytest.raises(ValueError, match="prohibited"):
        agent.execute(mission_id="mission-1")

    assert len(model.calls) == 1
