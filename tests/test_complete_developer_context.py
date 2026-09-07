from pathlib import Path

import pytest

from ai_hq.code_changes.context import RepositoryContextProvider
from ai_hq.delivery.model_agents import ModelBackedDeveloperAgent


class FakeModel:
    def __init__(self, response: str):
        self.response = response
        self.messages = None

    def reply(self, system_prompt, messages):
        self.messages = messages
        return self.response


def test_context_never_exposes_truncated_file_as_writable(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()

    small = source / "small.css"
    small.write_text(
        ".toolbar { height: 50px; }\n",
        encoding="utf-8",
    )

    large = source / "watch.html"
    large.write_text(
        "toolbar " + ("x" * 10_000),
        encoding="utf-8",
    )

    provider = RepositoryContextProvider(
        repository="dripvid",
        source_path=source,
        max_chars_per_file=100,
        max_total_chars=500,
    )

    context = provider.build(
        instruction="make toolbar smaller"
    )

    files = {
        item["path"]: item
        for item in context["files"]
    }

    assert files["small.css"]["complete"] is True

    # Large/truncated files must not be presented as writable source.
    assert (
        "watch.html" not in files
        or files["watch.html"]["complete"] is False
    )


def test_developer_rejects_write_to_file_not_in_complete_context():
    context = {
        "repository": "dripvid",
        "instruction": "make toolbar smaller",
        "files": [
            {
                "path": "public/css/app.css",
                "content": ".toolbar { height: 50px; }\n",
                "complete": True,
            }
        ],
    }

    model = FakeModel(
        """{
            "summary": "Change toolbar",
            "changes": [
                {
                    "path": "public/watch.html",
                    "operation": "write",
                    "content": "<html></html>"
                }
            ]
        }"""
    )

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=lambda mission_id: context,
    )

    with pytest.raises(
        ValueError,
        match="complete trusted context",
    ):
        agent.execute(mission_id="mission-1")


def test_developer_allows_write_to_complete_context_file():
    context = {
        "repository": "dripvid",
        "instruction": "make toolbar smaller",
        "files": [
            {
                "path": "public/css/app.css",
                "content": ".toolbar { height: 50px; }\n",
                "complete": True,
            }
        ],
    }

    model = FakeModel(
        """{
            "summary": "Reduce toolbar height",
            "changes": [
                {
                    "path": "public/css/app.css",
                    "operation": "write",
                    "content": ".toolbar { height: 44px; }\\n"
                }
            ]
        }"""
    )

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=lambda mission_id: context,
    )

    result = agent.execute(
        mission_id="mission-1"
    )

    assert result["changes"] == [
        {
            "path": "public/css/app.css",
            "operation": "write",
            "content": ".toolbar { height: 44px; }\n",
        }
    ]


def test_developer_rejects_delete_without_complete_context():
    context = {
        "repository": "dripvid",
        "instruction": "remove obsolete component",
        "files": [],
    }

    model = FakeModel(
        """{
            "summary": "Remove file",
            "changes": [
                {
                    "path": "public/watch.html",
                    "operation": "delete",
                    "content": null
                }
            ]
        }"""
    )

    agent = ModelBackedDeveloperAgent(
        model,
        context_provider=lambda mission_id: context,
    )

    with pytest.raises(
        ValueError,
        match="complete trusted context",
    ):
        agent.execute(mission_id="mission-1")
