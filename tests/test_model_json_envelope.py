import json

import pytest

from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent


class StaticModelClient:
    def __init__(self, response: str):
        self.response = response

    def reply(self, _system_prompt, _messages):
        return self.response


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
