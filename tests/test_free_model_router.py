from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_hq.chat.free_model_router import FreeModelProvider, FreeModelRouter
from ai_hq.chat.model_client import ChatModelError


@dataclass
class StubClient:
    result: str | None = None
    error: Exception | None = None
    calls: int = 0

    def reply(self, system_prompt, messages):
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def provider(name: str, client: StubClient) -> FreeModelProvider:
    return FreeModelProvider(
        name=name,
        client=client,
        zero_cost_policy="explicitly_free",
    )


def test_first_available_provider_wins():
    local = StubClient(result="local reply")
    groq = StubClient(result="groq reply")

    router = FreeModelRouter(
        [
            provider("local", local),
            provider("groq", groq),
        ]
    )

    assert router.reply(
        "You are SysAdmin.",
        [{"role": "user", "content": "Hello"}],
    ) == "local reply"

    assert local.calls == 1
    assert groq.calls == 0


def test_router_fails_over_after_provider_error():
    local = StubClient(error=ChatModelError("local unavailable"))
    groq = StubClient(result="groq reply")

    router = FreeModelRouter(
        [
            provider("local", local),
            provider("groq", groq),
        ]
    )

    assert router.reply(
        "You are SysAdmin.",
        [{"role": "user", "content": "Hello"}],
    ) == "groq reply"

    assert local.calls == 1
    assert groq.calls == 1


def test_router_preserves_provider_order():
    attempts = []

    class RecordingClient:
        def __init__(self, name, succeeds=False):
            self.name = name
            self.succeeds = succeeds

        def reply(self, system_prompt, messages):
            attempts.append(self.name)
            if self.succeeds:
                return f"{self.name} reply"
            raise ChatModelError("unavailable")

    router = FreeModelRouter(
        [
            FreeModelProvider(
                name="local",
                client=RecordingClient("local"),
                zero_cost_policy="local",
            ),
            FreeModelProvider(
                name="groq",
                client=RecordingClient("groq"),
                zero_cost_policy="explicitly_free",
            ),
            FreeModelProvider(
                name="openrouter",
                client=RecordingClient("openrouter", succeeds=True),
                zero_cost_policy="explicitly_free",
            ),
        ]
    )

    assert router.reply(
        "System",
        [{"role": "user", "content": "Hi"}],
    ) == "openrouter reply"

    assert attempts == ["local", "groq", "openrouter"]


def test_all_provider_failures_raise_safe_error():
    secret = "THIS_SECRET_MUST_NEVER_ESCAPE"

    router = FreeModelRouter(
        [
            provider(
                "groq",
                StubClient(
                    error=ChatModelError(
                        f"provider failed with bearer token {secret}"
                    )
                ),
            ),
            provider(
                "openrouter",
                StubClient(error=ChatModelError("quota exhausted")),
            ),
        ]
    )

    with pytest.raises(ChatModelError) as exc_info:
        router.reply(
            "System",
            [{"role": "user", "content": "Hi"}],
        )

    message = str(exc_info.value)

    assert "groq" in message
    assert "openrouter" in message
    assert secret not in message


@pytest.mark.parametrize(
    "policy",
    [
        "paid",
        "unknown",
        "cheapest",
        "automatic",
    ],
)
def test_paid_or_unknown_policy_is_rejected(policy):
    with pytest.raises(ValueError, match="zero-cost"):
        FreeModelProvider(
            name="unsafe-provider",
            client=StubClient(result="should never run"),
            zero_cost_policy=policy,
        )
