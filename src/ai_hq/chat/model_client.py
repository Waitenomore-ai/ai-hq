from __future__ import annotations

from typing import Protocol

import httpx

from ai_hq.config import Settings


class ChatModelError(RuntimeError):
    """Safe boundary error for chat model invocation."""


class ChatModelClient(Protocol):
    def reply(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        ...


class OpenAICompatibleChatModelClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def reply(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                *messages,
            ],
        }

        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

        except httpx.TimeoutException as exc:
            raise ChatModelError(
                "Chat model request timed out"
            ) from exc

        except httpx.HTTPStatusError as exc:
            raise ChatModelError(
                "Chat model provider request failed"
            ) from exc

        except httpx.HTTPError as exc:
            raise ChatModelError(
                "Chat model provider request failed"
            ) from exc

        try:
            data = response.json()
            choices = data["choices"]

            if not isinstance(choices, list) or not choices:
                raise ValueError("missing choices")

            message = choices[0]["message"]
            content = message["content"]

            if not isinstance(content, str) or not content.strip():
                raise ValueError("missing content")

        except (KeyError, TypeError, ValueError) as exc:
            raise ChatModelError(
                "Chat model returned an invalid response"
            ) from exc

        return content.strip()


def build_chat_model_client(
    settings: Settings,
) -> ChatModelClient | None:
    if not settings.chat_model_base_url:
        return None

    if not settings.chat_model_name:
        raise ValueError(
            "AI_HQ_CHAT_MODEL_NAME is required when "
            "AI_HQ_CHAT_MODEL_BASE_URL is configured"
        )

    return OpenAICompatibleChatModelClient(
        base_url=settings.chat_model_base_url,
        model=settings.chat_model_name,
        api_key=settings.chat_model_api_key,
        timeout_seconds=settings.chat_model_timeout_seconds,
    )
