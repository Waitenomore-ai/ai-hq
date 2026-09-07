import json

from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent


class FakeModelClient:
    def __init__(self):
        self.messages = None

    def reply(self, system_prompt, messages):
        self.messages = messages

        return json.dumps(
            {
                "summary": "Update toolbar",
                "changes": [
                    {
                        "path": "public/nav.css",
                        "operation": "write",
                        "content": ".toolbar { height: 60px; }",
                    }
                ],
            }
        )


def test_developer_receives_bounded_repository_context():
    model = FakeModelClient()

    def context_provider(mission_id):
        assert mission_id == "mission-1"

        return {
            "repository": "dripvid",
            "instruction": "Make the toolbar smaller",
            "files": [
                {
                    "path": "public/nav.css",
                    "content": ".toolbar { height: 80px; }",
                }
            ],
        }

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=context_provider,
    )

    candidate = agent.execute(
        mission_id="mission-1"
    )

    payload = json.loads(
        model.messages[0]["content"]
    )

    assert payload["mission_id"] == "mission-1"
    assert payload["repository_context"]["repository"] == "dripvid"
    assert (
        payload["repository_context"]["instruction"]
        == "Make the toolbar smaller"
    )

    assert candidate["summary"] == "Update toolbar"


def test_developer_context_cannot_supply_command_authority():
    model = FakeModelClient()

    def context_provider(_mission_id):
        return {
            "repository": "dripvid",
            "instruction": "change toolbar",
            "files": [],
            "command": "rm -rf /",
        }

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=context_provider,
    )

    agent.execute(
        mission_id="mission-1"
    )

    payload = json.loads(
        model.messages[0]["content"]
    )

    assert "command" not in payload["repository_context"]
