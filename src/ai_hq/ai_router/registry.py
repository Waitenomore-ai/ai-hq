from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum


class ProviderKind(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    provider: str
    model: str
    capabilities: frozenset[object]
    priority: int = 100
    provider_kind: ProviderKind = ProviderKind.CLOUD
    enabled: bool = True
    requires_payment: bool = False
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


@dataclass(slots=True)
class ModelRegistry:
    endpoints: list[ModelEndpoint] = field(default_factory=list)

    def __init__(self, endpoints: Iterable[ModelEndpoint] = ()) -> None:
        self.endpoints = list(endpoints)
        self._availability: dict[tuple[str, str], bool] = {}

    def set_availability(self, provider: str, model: str, available: bool) -> None:
        self._availability[(provider, model)] = available

    def is_available(self, endpoint: ModelEndpoint) -> bool:
        return self._availability.get((endpoint.provider, endpoint.model), True)

    def candidates_for(self, capability: object) -> list[ModelEndpoint]:
        return [
            endpoint
            for endpoint in self.endpoints
            if endpoint.enabled
            and capability in endpoint.capabilities
            and self.is_available(endpoint)
        ]
