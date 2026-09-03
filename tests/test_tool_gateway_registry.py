import pytest
from ai_hq.tool_gateway.contracts import ToolRequest
from ai_hq.tool_gateway.registry import ToolRegistry


class FakeAdapter:
    def __init__(self, capability: str):
        self.capability = capability

    def execute(self, request: ToolRequest) -> dict[str, object]:
        return {"capability": request.capability}


def test_registry_resolves_only_exact_capability():
    registry = ToolRegistry([FakeAdapter("host.health")])

    assert registry.resolve("host.health") is not None
    assert registry.resolve("host.*") is None
    assert registry.resolve("host.health.extra") is None


def test_duplicate_capability_registration_is_rejected():
    with pytest.raises(ValueError, match="duplicate capability"):
        ToolRegistry([FakeAdapter("host.health"), FakeAdapter("host.health")])


def test_empty_or_wildcard_capability_registration_is_rejected():
    for capability in ("", "*", "host.*"):
        with pytest.raises(ValueError, match="capability"):
            ToolRegistry([FakeAdapter(capability)])
