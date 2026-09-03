from __future__ import annotations

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
    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def route(self, capability: CapabilityClass) -> RouteDecision:
        candidates = self.registry.candidates_for(capability)
        considered = len(candidates)

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
                candidates_considered=considered if considered else 0,
            )

        selected = min(
            candidates,
            key=lambda endpoint: (
                endpoint.priority,
                endpoint.provider,
                endpoint.model,
            ),
        )
        return RouteDecision(
            endpoint=selected,
            reason="selected",
            candidates_considered=considered,
        )
