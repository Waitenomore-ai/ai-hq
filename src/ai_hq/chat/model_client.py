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
    from ai_hq.chat.free_model_router import (
        FreeModelProvider,
        FreeModelRouter,
    )

    providers: list[FreeModelProvider] = []

    timeout = settings.free_ai_timeout_seconds

    # 1. Local OpenAI-compatible inference.
    if settings.free_ai_local_base_url:
        if not settings.free_ai_local_model:
            raise ValueError(
                "AI_HQ_FREE_AI_LOCAL_MODEL is required when "
                "AI_HQ_FREE_AI_LOCAL_BASE_URL is configured"
            )

        providers.append(
            FreeModelProvider(
                name="local",
                client=OpenAICompatibleChatModelClient(
                    base_url=settings.free_ai_local_base_url,
                    model=settings.free_ai_local_model,
                    api_key=settings.free_ai_local_api_key,
                    timeout_seconds=timeout,
                ),
                zero_cost_policy="local",
            )
        )

    # 2. Groq free allowance.
    if settings.free_ai_groq_api_key:
        if not settings.free_ai_groq_model:
            raise ValueError(
                "AI_HQ_FREE_AI_GROQ_MODEL is required when "
                "AI_HQ_FREE_AI_GROQ_API_KEY is configured"
            )

        providers.append(
            FreeModelProvider(
                name="groq",
                client=OpenAICompatibleChatModelClient(
                    base_url="https://api.groq.com/openai/v1",
                    model=settings.free_ai_groq_model,
                    api_key=settings.free_ai_groq_api_key,
                    timeout_seconds=timeout,
                ),
                zero_cost_policy="free_allowance",
            )
        )

    # 3. OpenRouter's explicitly free router.
    #
    # The model identifier is deliberately not configurable.
    # This prevents configuration from silently substituting a paid
    # OpenRouter model.
    if settings.free_ai_openrouter_api_key:
        providers.append(
            FreeModelProvider(
                name="openrouter",
                client=OpenAICompatibleChatModelClient(
                    base_url="https://openrouter.ai/api/v1",
                    model="openrouter/free",
                    api_key=settings.free_ai_openrouter_api_key,
                    timeout_seconds=timeout,
                ),
                zero_cost_policy="explicitly_free",
            )
        )

    # 4. Hugging Face requires an explicitly selected model.
    if settings.free_ai_hf_token:
        if not settings.free_ai_hf_model:
            raise ValueError(
                "AI_HQ_FREE_AI_HF_MODEL is required when "
                "AI_HQ_FREE_AI_HF_TOKEN is configured"
            )

        providers.append(
            FreeModelProvider(
                name="huggingface",
                client=OpenAICompatibleChatModelClient(
                    base_url="https://router.huggingface.co/v1",
                    model=settings.free_ai_hf_model,
                    api_key=settings.free_ai_hf_token,
                    timeout_seconds=timeout,
                ),
                zero_cost_policy="free_allowance",
            )
        )

    if providers:
        return FreeModelRouter(providers)

    # Backwards compatibility with the original single-provider
    # configuration. It remains separate from FreeModelRouter because
    # legacy configuration is not automatically classified as free.
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
