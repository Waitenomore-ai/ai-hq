import pytest

from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry


def make_target(**changes):
    values = {
        "key": "ai-hq",
        "service_unit": "ai-hq.service",
        "allowed_capabilities": frozenset({"service.status.read"}),
    }
    values.update(changes)
    return OperationalTarget(**values)


def test_registry_resolves_registered_logical_target():
    target = make_target()
    registry = OperationalTargetRegistry([target])

    assert registry.resolve("ai-hq") is target
    assert registry.require("ai-hq") is target


def test_registry_rejects_unknown_target():
    registry = OperationalTargetRegistry([])

    assert registry.resolve("not-registered") is None

    with pytest.raises(ValueError, match="unknown operational target"):
        registry.require("not-registered")


def test_target_rejects_empty_key():
    with pytest.raises(ValueError):
        make_target(key="")


def test_target_rejects_empty_service_unit():
    with pytest.raises(ValueError):
        make_target(service_unit="")


def test_target_rejects_wildcard_capability():
    with pytest.raises(ValueError):
        make_target(allowed_capabilities=frozenset({"*"}))


def test_registry_rejects_duplicate_target_key():
    with pytest.raises(ValueError, match="duplicate operational target"):
        OperationalTargetRegistry([make_target(), make_target()])


def test_target_capability_must_be_explicit():
    target = make_target()

    assert target.allows("service.status.read")
    assert not target.allows("service.restart")
