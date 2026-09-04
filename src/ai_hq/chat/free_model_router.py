from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ai_hq.chat.model_client import ChatModelClient, ChatModelError


ALLOWED_ZERO_COST_POLICIES = frozenset(
    {
        "local",
        "explicitly_free",
        "free_allowance",
    }
)


@dataclass(frozen=True)
class FreeModelProvider:
    """One explicitly zero-cost model provider used by FreeModelRouter."""

    name: str
    client: ChatModelClient
    zero_cost_policy: str

    def __post_init__(self) -> None:
        name = self.name.strip()

        if not name:
            raise ValueError("provider name must not be empty")

        if self.zero_cost_policy not in ALLOWED_ZERO_COST_POLICIES:
            raise ValueError(
                "provider must use an approved zero-cost policy"
            )


class FreeModelRouter:
    """
    Try explicitly zero-cost model providers in deterministic order.

    The router never changes models, upgrades providers, or attempts a
    paid fallback. Provider failures are deliberately summarized without
    including the provider's raw exception text so credentials or other
    sensitive response data cannot leak through aggregate errors.
    """

    def __init__(
        self,
        providers: Sequence[FreeModelProvider],
    ) -> None:
        self._providers = tuple(providers)

        if not self._providers:
            raise ValueError(
                "FreeModelRouter requires at least one zero-cost provider"
            )

    @property
    def providers(self) -> tuple[FreeModelProvider, ...]:
        return self._providers

    def reply(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        failed_provider_names: list[str] = []

        for provider in self._providers:
            try:
                return provider.client.reply(system_prompt, messages)
            except ChatModelError:
                failed_provider_names.append(provider.name)

        names = ", ".join(failed_provider_names)

        raise ChatModelError(
            "all configured free AI providers are temporarily "
            f"unavailable: {names}"
        )
