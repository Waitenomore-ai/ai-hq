import json
from pathlib import Path

from ai_hq.code_changes.context import RepositoryContextProvider
from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent


class CapturingModel:
    def __init__(self):
        self.system_prompt = None
        self.messages = None

    def reply(self, system_prompt, messages):
        self.system_prompt = system_prompt
        self.messages = messages

        return json.dumps(
            {
                "summary": "Use the available CSS file",
                "changes": [],
            }
        )


def test_default_context_can_supply_medium_complete_css_file(
    tmp_path: Path,
):
    source = tmp_path / "repo"
    css = source / "public" / "css" / "mobile-member.css"

    css.parent.mkdir(parents=True)

    content = (
        ".member-top { padding: .8rem 1rem; }\n"
        + ("/* safe styling context */\n" * 300)
    )

    assert len(content) > 6000
    assert len(content) < 12000

    css.write_text(content, encoding="utf-8")

    provider = RepositoryContextProvider(
        repository="dripvid",
        source_path=source,
    )

    context = provider.build(
        instruction=(
            "Make the DripVid member toolbar slightly smaller "
            "using CSS"
        )
    )

    files = {
        item["path"]: item
        for item in context["files"]
    }

    assert "public/css/mobile-member.css" in files
    assert files["public/css/mobile-member.css"]["complete"] is True
    assert (
        files["public/css/mobile-member.css"]["content"]
        == content
    )


def test_developer_receives_explicit_writable_paths():
    model = CapturingModel()

    context = {
        "repository": "dripvid",
        "instruction": "Make the member toolbar smaller",
        "files": [
            {
                "path": "public/css/mobile-member.css",
                "content": (
                    ".member-top { padding: .8rem 1rem; }\n"
                ),
                "complete": True,
            }
        ],
    }

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=lambda _mission_id: context,
    )

    agent.execute(mission_id="mission-1")

    payload = json.loads(
        model.messages[0]["content"]
    )

    repository_context = payload["repository_context"]

    assert repository_context["writable_paths"] == [
        "public/css/mobile-member.css"
    ]


def test_developer_prompt_prefers_css_for_visual_changes():
    model = CapturingModel()

    context = {
        "repository": "dripvid",
        "instruction": "Make the member toolbar smaller",
        "files": [
            {
                "path": "public/css/mobile-member.css",
                "content": (
                    ".member-top { padding: .8rem 1rem; }\n"
                ),
                "complete": True,
            }
        ],
    }

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=lambda _mission_id: context,
    )

    agent.execute(mission_id="mission-1")

    prompt = model.system_prompt.casefold()

    assert "writable_paths" in prompt
    assert "visual" in prompt
    assert "css" in prompt
    assert "empty changes" in prompt


def test_no_suitable_writable_file_can_return_no_changes():
    model = CapturingModel()

    context = {
        "repository": "dripvid",
        "instruction": "Make the member toolbar smaller",
        "files": [],
    }

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=lambda _mission_id: context,
    )

    result = agent.execute(
        mission_id="mission-1"
    )

    assert result == {
        "summary": "Use the available CSS file",
        "changes": [],
    }
