import httpx
import pytest

from ai_hq.chat.model_client import (
    ChatModelError,
    OpenAICompatibleChatModelClient,
    build_chat_model_client,
)
from ai_hq.config import Settings


def settings(**overrides):
    values = {
        "database_url": "sqlite://",
        "redis_url": "redis://localhost:6379/0",
        "chat_model_base_url": None,
        "chat_model_name": None,
        "chat_model_api_key": None,
        "chat_model_timeout_seconds": 15.0,
    }
    values.update(overrides)
    return Settings(**values)


def test_missing_provider_returns_none():
    assert build_chat_model_client(settings()) is None


def test_configured_provider_builds_client():
    client = build_chat_model_client(
        settings(
            chat_model_base_url="http://model.local/v1",
            chat_model_name="test-model",
        )
    )

    assert isinstance(client, OpenAICompatibleChatModelClient)
    assert client.model == "test-model"


def test_provider_requires_model_name():
    with pytest.raises(ValueError):
        build_chat_model_client(
            settings(
                chat_model_base_url="http://model.local/v1",
                chat_model_name=None,
            )
        )


def test_reply_posts_openai_compatible_payload_and_extracts_text():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = request.read().decode()

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "AI HQ is responding normally.",
                        }
                    }
                ]
            },
        )

    client = OpenAICompatibleChatModelClient(
        base_url="http://model.local/v1",
        model="test-model",
        api_key="secret-test-key",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    reply = client.reply(
        "You are SysAdmin.",
        [{"role": "user", "content": "Hello"}],
    )

    assert reply == "AI HQ is responding normally."
    assert captured["method"] == "POST"
    assert captured["url"] == "http://model.local/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret-test-key"
    assert '"model":"test-model"' in captured["body"]
    assert '"content":"You are SysAdmin."' in captured["body"]
    assert '"content":"Hello"' in captured["body"]


def test_api_key_is_optional_for_local_provider():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Local model reply",
                        }
                    }
                ]
            },
        )

    client = OpenAICompatibleChatModelClient(
        base_url="http://127.0.0.1:11434/v1",
        model="local-model",
        api_key=None,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    assert client.reply(
        "System",
        [{"role": "user", "content": "Hi"}],
    ) == "Local model reply"

    assert captured["authorization"] is None


def test_http_failure_is_converted_to_chat_model_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"message": "provider unavailable"}},
        )

    client = OpenAICompatibleChatModelClient(
        base_url="http://model.local/v1",
        model="test-model",
        api_key=None,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ChatModelError, match="provider request failed"):
        client.reply(
            "System",
            [{"role": "user", "content": "Hi"}],
        )


def test_timeout_is_converted_to_chat_model_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = OpenAICompatibleChatModelClient(
        base_url="http://model.local/v1",
        model="test-model",
        api_key=None,
        timeout_seconds=0.1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ChatModelError, match="timed out"):
        client.reply(
            "System",
            [{"role": "user", "content": "Hi"}],
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_invalid_provider_response_is_rejected(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = OpenAICompatibleChatModelClient(
        base_url="http://model.local/v1",
        model="test-model",
        api_key=None,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ChatModelError, match="invalid response"):
        client.reply(
            "System",
            [{"role": "user", "content": "Hi"}],
        )


def test_build_chat_model_client_uses_local_free_provider_first():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_local_base_url="http://127.0.0.1:11434/v1",
        free_ai_local_model="local-model",
        free_ai_local_api_key=None,
        free_ai_groq_api_key="groq-secret",
        free_ai_groq_model="groq-model",
        free_ai_openrouter_api_key="openrouter-secret",
        free_ai_hf_token="hf-secret",
        free_ai_hf_model="hf-model",
    )

    client = build_chat_model_client(settings)

    assert isinstance(client, FreeModelRouter)

    providers = client.providers

    assert [provider.name for provider in providers] == [
        "local",
        "groq",
        "openrouter",
        "huggingface",
    ]

    assert providers[0].client.base_url == "http://127.0.0.1:11434/v1"
    assert providers[0].client.model == "local-model"
    assert providers[0].zero_cost_policy == "local"


def test_build_chat_model_client_configures_groq():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_groq_api_key="groq-secret",
        free_ai_groq_model="groq-model",
    )

    client = build_chat_model_client(settings)

    assert isinstance(client, FreeModelRouter)
    assert len(client.providers) == 1

    provider = client.providers[0]

    assert provider.name == "groq"
    assert provider.client.base_url == "https://api.groq.com/openai/v1"
    assert provider.client.model == "groq-model"
    assert provider.client.api_key == "groq-secret"
    assert provider.zero_cost_policy == "free_allowance"


def test_build_chat_model_client_locks_openrouter_to_free_router():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_openrouter_api_key="openrouter-secret",
    )

    client = build_chat_model_client(settings)

    assert isinstance(client, FreeModelRouter)
    assert len(client.providers) == 1

    provider = client.providers[0]

    assert provider.name == "openrouter"
    assert provider.client.base_url == "https://openrouter.ai/api/v1"
    assert provider.client.model == "openrouter/free"
    assert provider.client.api_key == "openrouter-secret"
    assert provider.zero_cost_policy == "explicitly_free"


def test_build_chat_model_client_configures_explicit_huggingface_route():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_hf_token="hf-secret",
        free_ai_hf_model="explicit-free-model",
    )

    client = build_chat_model_client(settings)

    assert isinstance(client, FreeModelRouter)
    assert len(client.providers) == 1

    provider = client.providers[0]

    assert provider.name == "huggingface"
    assert provider.client.base_url == "https://router.huggingface.co/v1"
    assert provider.client.model == "explicit-free-model"
    assert provider.client.api_key == "hf-secret"
    assert provider.zero_cost_policy == "free_allowance"


def test_unconfigured_free_providers_are_skipped():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_openrouter_api_key="openrouter-secret",
    )

    client = build_chat_model_client(settings)

    assert isinstance(client, FreeModelRouter)
    assert [provider.name for provider in client.providers] == [
        "openrouter",
    ]


def test_legacy_chat_model_is_used_only_without_free_providers():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    legacy_only = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        chat_model_base_url="http://legacy.local/v1",
        chat_model_name="legacy-model",
        chat_model_api_key="legacy-secret",
    )

    legacy_client = build_chat_model_client(legacy_only)

    assert isinstance(
        legacy_client,
        OpenAICompatibleChatModelClient,
    )
    assert legacy_client.model == "legacy-model"

    free_and_legacy = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        chat_model_base_url="http://legacy.local/v1",
        chat_model_name="legacy-model",
        chat_model_api_key="legacy-secret",
        free_ai_openrouter_api_key="openrouter-secret",
    )

    free_client = build_chat_model_client(free_and_legacy)

    assert isinstance(free_client, FreeModelRouter)
    assert [provider.name for provider in free_client.providers] == [
        "openrouter",
    ]


def test_local_provider_requires_model_when_base_url_is_configured():
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_local_base_url="http://127.0.0.1:11434/v1",
        free_ai_local_model=None,
    )

    with pytest.raises(
        ValueError,
        match="FREE_AI_LOCAL_MODEL",
    ):
        build_chat_model_client(settings)


def test_groq_requires_model_when_key_is_configured():
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_groq_api_key="groq-secret",
        free_ai_groq_model=None,
    )

    with pytest.raises(
        ValueError,
        match="FREE_AI_GROQ_MODEL",
    ):
        build_chat_model_client(settings)


def test_huggingface_requires_explicit_model():
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_hf_token="hf-secret",
        free_ai_hf_model=None,
    )

    with pytest.raises(
        ValueError,
        match="FREE_AI_HF_MODEL",
    ):
        build_chat_model_client(settings)


def test_openrouter_free_model_identifier_cannot_be_configured():
    from ai_hq.chat.free_model_router import FreeModelRouter
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        free_ai_openrouter_api_key="openrouter-secret",
    )

    assert not hasattr(settings, "free_ai_openrouter_model")

    client = build_chat_model_client(settings)

    assert isinstance(client, FreeModelRouter)
    assert client.providers[0].client.model == "openrouter/free"


def test_no_paid_free_ai_setting_exists():
    from ai_hq.config import Settings

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
    )

    forbidden = [
        "free_ai_allow_paid",
        "free_ai_paid_fallback",
        "free_ai_enable_billing",
        "free_ai_fallback_to_paid",
    ]

    for name in forbidden:
        assert not hasattr(settings, name)
