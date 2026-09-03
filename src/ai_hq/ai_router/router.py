from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ai_hq.ai_router.registry import ModelEndpoint, ModelRegistry, ProviderKind


class CapabilityClass(str, Enum):
    CLASSIFICATION = "classification"
    FAST_REASONING = "fast_reasoning"
    COMPLEX_REASONING = "complex_reasoning"
    LONG_CONTEXT_ANALYSIS = "long_context_analysis"
    LOCAL_PRIVATE = "local_private"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    endpoint: ModelEndpoint | None
    reason: str
    candidates_considered: int


class ModelRouter:
    def __init__(
        self,
        registry: ModelRegistry,
        *,
        allow_paid: bool = False,
        prefer_local: bool = True,
        budget_check: Callable[[float], tuple[bool, str]] | None = None,
    ) -> None:
        self.registry = registry
        self.allow_paid = allow_paid
        self.prefer_local = prefer_local
        self.budget_check = budget_check

    def route(
        self,
        capability: CapabilityClass,
        *,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
    ) -> RouteDecision:
        candidates = self.registry.candidates_for(capability)
        considered = len(candidates)

        if not self.allow_paid:
            candidates = [endpoint for endpoint in candidates if not endpoint.requires_payment]

        if capability is CapabilityClass.LOCAL_PRIVATE:
            candidates = [
                endpoint
                for endpoint in candidates
                if endpoint.provider_kind is ProviderKind.LOCAL
            ]

        if not candidates:
            return RouteDecision(
                endpoint=None,
                reason="no_available_model",
                candidates_considered=considered,
            )

        ordered = sorted(
            candidates,
            key=lambda endpoint: (
                0
                if self.prefer_local and endpoint.provider_kind is ProviderKind.LOCAL
                else 1,
                endpoint.priority,
                endpoint.provider,
                endpoint.model,
            ),
        )
        last_denial_reason = "no_available_model"
        for endpoint in ordered:
            estimated_cost = (
                estimated_input_tokens / 1_000_000 * endpoint.input_cost_per_million
                + estimated_output_tokens / 1_000_000 * endpoint.output_cost_per_million
            )
            if self.budget_check is not None:
                allowed, reason = self.budget_check(estimated_cost)
                if not allowed:
                    last_denial_reason = reason
                    continue
            return RouteDecision(
                endpoint=endpoint,
                reason="selected",
                candidates_considered=considered,
            )

        return RouteDecision(
            endpoint=None,
            reason=last_denial_reason,
            candidates_considered=considered,
        )
