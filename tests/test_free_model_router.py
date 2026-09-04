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


def test_provider_collection_is_immutable():
    client = StubClient(result="reply")
    router = FreeModelRouter([provider("openrouter", client)])

    assert isinstance(router.providers, tuple)

    with pytest.raises(AttributeError):
        router.providers.append(provider("paid", client))


def test_provider_policy_cannot_be_changed_after_creation():
    item = provider("openrouter", StubClient(result="reply"))

    with pytest.raises(Exception):
        item.zero_cost_policy = "paid"


def test_router_never_uses_raw_provider_error_in_aggregate_failure():
    sensitive_values = [
        "sk-secret-openrouter-key",
        "gsk_secret_groq_key",
        "hf_secret_token",
        "Bearer super-secret",
        "https://user:password@example.invalid",
    ]

    providers = []

    for index, secret in enumerate(sensitive_values):
        providers.append(
            provider(
                f"provider-{index}",
                StubClient(
                    error=ChatModelError(
                        f"request failed: {secret}"
                    )
                ),
            )
        )

    router = FreeModelRouter(providers)

    with pytest.raises(ChatModelError) as exc_info:
        router.reply(
            "System",
            [{"role": "user", "content": "Hello"}],
        )

    message = str(exc_info.value)

    for secret in sensitive_values:
        assert secret not in message

    for index in range(len(sensitive_values)):
        assert f"provider-{index}" in message


def test_router_does_not_retry_provider_with_different_model():
    calls = []

    class ModelRecordingClient:
        model = "openrouter/free"

        def reply(self, system_prompt, messages):
            calls.append(self.model)
            raise ChatModelError("quota exhausted")

    router = FreeModelRouter(
        [
            FreeModelProvider(
                name="openrouter",
                client=ModelRecordingClient(),
                zero_cost_policy="explicitly_free",
            )
        ]
    )

    with pytest.raises(ChatModelError):
        router.reply(
            "System",
            [{"role": "user", "content": "Hello"}],
        )

    assert calls == ["openrouter/free"]


def test_router_rejects_empty_provider_list():
    with pytest.raises(
        ValueError,
        match="at least one zero-cost provider",
    ):
        FreeModelRouter([])


def test_only_documented_zero_cost_policies_are_accepted():
    accepted = {
        "local",
        "explicitly_free",
        "free_allowance",
    }

    for policy in accepted:
        item = FreeModelProvider(
            name=f"provider-{policy}",
            client=StubClient(result="ok"),
            zero_cost_policy=policy,
        )
        assert item.zero_cost_policy == policy

    rejected = {
        "paid",
        "metered",
        "cheapest",
        "automatic",
        "premium",
        "fallback",
        "",
    }

    for policy in rejected:
        with pytest.raises(ValueError, match="zero-cost"):
            FreeModelProvider(
                name=f"provider-{policy or 'empty'}",
                client=StubClient(result="never"),
                zero_cost_policy=policy,
            )
