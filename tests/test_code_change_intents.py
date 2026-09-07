import pytest

from ai_hq.chat.intents import plan_sysadmin_intent


@pytest.mark.parametrize(
    ("text", "repository"),
    [
        ("Make the DripVid toolbar smaller", "dripvid"),
        ("Change the AI HQ dashboard layout", "ai-hq"),
        ("Fix this UI bug in DripVid", "dripvid"),
        ("Edit the HQ sidebar", "ai-hq"),
        ("Adjust the DripVid menu spacing", "dripvid"),
    ],
)
def test_code_change_requests_resolve_trusted_repository(text, repository):
    intent = plan_sysadmin_intent(text)

    assert intent.kind == "code_change"
    assert intent.repository == repository
    assert intent.steps == ()
    assert intent.refusal_reason is None


def test_code_change_request_cannot_target_both_repositories():
    intent = plan_sysadmin_intent(
        "Change the AI HQ dashboard and the DripVid toolbar"
    )

    assert intent.kind == "refused"
    assert intent.repository is None
    assert intent.steps == ()
    assert intent.refusal_reason
    assert "repository" in intent.refusal_reason.lower()


def test_code_change_without_trusted_repository_fails_closed():
    intent = plan_sysadmin_intent(
        "Change the dashboard layout and make the toolbar smaller"
    )

    assert intent.kind == "refused"
    assert intent.repository is None
    assert intent.steps == ()
    assert intent.refusal_reason
    assert "repository" in intent.refusal_reason.lower()


def test_existing_shell_boundary_remains_enforced():
    intent = plan_sysadmin_intent(
        "Run shell command uname -a"
    )

    assert intent.kind == "refused"
    assert intent.repository is None
    assert intent.steps == ()


def test_existing_operational_read_intent_is_unchanged():
    intent = plan_sysadmin_intent(
        "Check system health"
    )

    assert intent.kind == "operational"
    assert intent.repository is None
    assert [step["tool_name"] for step in intent.steps] == [
        "system.health.read"
    ]


def test_normal_conversation_is_unchanged():
    intent = plan_sysadmin_intent(
        "Hello HQ, what can you help me with?"
    )

    assert intent.kind == "conversation"
    assert intent.repository is None
    assert intent.steps == ()
