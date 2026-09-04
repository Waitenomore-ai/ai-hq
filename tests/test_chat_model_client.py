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
