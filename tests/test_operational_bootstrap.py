from dataclasses import dataclass

import pytest

from ai_hq.operations.bootstrap import (
    build_operational_tool_registry,
    operational_adapters,
)
from ai_hq.operations.targets import (
    OperationalTarget,
    OperationalTargetRegistry,
)
from ai_hq.tool_gateway.registry import ToolRegistry


@dataclass
class FakeTransport:
    def system_health(self, target):
        return {}

    def service_status(self, target):
        return {}

    def service_logs(self, target, *, lines):
        return {}

    def service_restart(self, target):
        return {}


def targets():
    return OperationalTargetRegistry([
        OperationalTarget(
            key="ai-hq",
            service_unit="ai-hq.service",
            allowed_capabilities=frozenset({
                "system.health.read",
                "service.status.read",
                "service.logs.read",
                "service.restart",
            }),
        )
    ])


def test_builds_registry_with_exact_stage2_capabilities():
    registry = build_operational_tool_registry(
        targets=targets(),
        transport=FakeTransport(),
    )

    assert registry.resolve("system.health.read") is not None
    assert registry.resolve("service.status.read") is not None
    assert registry.resolve("service.logs.read") is not None
    assert registry.resolve("service.restart") is not None

    assert registry.resolve("shell.execute") is None
    assert registry.resolve("*") is None


def test_operational_adapters_can_join_existing_registry_at_construction():
    adapters = operational_adapters(
        targets=targets(),
        transport=FakeTransport(),
    )

    registry = ToolRegistry(adapters)

    assert registry.resolve("system.health.read") is not None
    assert registry.resolve("service.restart") is not None


def test_existing_registry_duplicate_protection_remains_authoritative():
    adapters = operational_adapters(
        targets=targets(),
        transport=FakeTransport(),
    )

    with pytest.raises(ValueError, match="duplicate capability"):
        ToolRegistry((*adapters, adapters[0]))


def test_registry_has_no_stage2_mutable_registration_backdoor():
    registry = build_operational_tool_registry(
        targets=targets(),
        transport=FakeTransport(),
    )

    assert not hasattr(registry, "register")
