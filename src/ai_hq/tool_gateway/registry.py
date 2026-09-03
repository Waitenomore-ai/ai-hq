from collections.abc import Iterable

from ai_hq.tool_gateway.contracts import ToolAdapter


class ToolRegistry:
    def __init__(self, adapters: Iterable[ToolAdapter] = ()) -> None:
        self._adapters: dict[str, ToolAdapter] = {}
        for adapter in adapters:
            capability = adapter.capability
            if not capability or "*" in capability:
                raise ValueError("invalid capability")
            if capability in self._adapters:
                raise ValueError("duplicate capability")
            self._adapters[capability] = adapter

    def resolve(self, capability: str) -> ToolAdapter | None:
        return self._adapters.get(capability)
