from dataclasses import dataclass, field

import pytest

from ai_hq.missions.models import MissionRisk
from ai_hq.operations.adapters import ServiceRecoverAdapter
from ai_hq.operations.bootstrap import build_operational_tool_registry
from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest


@dataclass
class RecordingTransport:
    calls: list[tuple] = field(default_factory=list)

    def service_recover(self, target, *, component):
        self.calls.append(("recover", target.key, component))
        return {
            "target": target.key,
            "component": component,
            "recovered": True,
        }

    def system_health(self, target):
        return {}

    def service_status(self, target):
        return {}

    def service_logs(self, target, *, lines):
        return {}

    def service_restart(self, target):
        return {}

    def deployment_deploy(self, target):
        return {}

    def deployment_rollback(self, target, release_id):
        return {}


def registry():
    return OperationalTargetRegistry(
        [
            OperationalTarget(
                key="dripvid",
                service_unit="dripvid.service",
                allowed_capabilities=frozenset(
                    {
                        "service.status.read",
                        "service.logs.read",
                        "service.recover",
                    }
                ),
            ),
            OperationalTarget(
                key="ai-hq",
                service_unit="ai-hq.service",
                allowed_capabilities=frozenset(
                    {
                        "service.status.read",
                        "service.recover",
                    }
                ),
            ),
            OperationalTarget(
                key="dripvid-read-only",
                service_unit="dripvid.service",
                allowed_capabilities=frozenset(
                    {
                        "service.status.read",
                    }
                ),
            ),
        ]
    )


def request(*, target="dripvid", params=None, mutates=True):
    return ToolRequest(
        mission_id="mission-recovery-1",
        agent_key="sysadmin",
        capability="service.recover",
        target=target,
        risk=MissionRisk.BLUE,
        params=params or {},
        conditions={},
        mutates_external_state=mutates,
    )


def test_service_recover_has_separate_exact_capability():
    assert ServiceRecoverAdapter.capability == "service.recover"


def test_recovery_calls_transport_with_only_fixed_component_key():
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    result = adapter.execute(
        request(params={"component": "app"})
    )

    assert result == {
        "target": "dripvid",
        "component": "app",
        "recovered": True,
    }
    assert transport.calls == [
        ("recover", "dripvid", "app"),
    ]


@pytest.mark.parametrize(
    "component",
    ["app", "mcp", "proxy", "tunnel", "database"],
)
def test_all_fixed_recovery_components_are_accepted(component):
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    adapter.execute(
        request(params={"component": component})
    )

    assert transport.calls == [
        ("recover", "dripvid", component),
    ]


def test_target_other_than_logical_dripvid_fails_closed():
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    with pytest.raises(ToolAdapterError, match="recovery_target_denied"):
        adapter.execute(
            request(
                target="ai-hq",
                params={"component": "app"},
            )
        )

    assert transport.calls == []


def test_target_without_exact_recovery_permission_fails_closed():
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    with pytest.raises(ToolAdapterError, match="target_capability_denied"):
        adapter.execute(
            request(
                target="dripvid-read-only",
                params={"component": "app"},
            )
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"component": "app", "unit": "dripvid.service"},
        {"component": "app", "command": "systemctl restart dripvid"},
        {"component": "app", "path": "/tmp/x"},
        {"component": "app", "host": "other-host"},
        {"unit": "nginx.service"},
    ],
)
def test_recovery_requires_exact_component_parameter(params):
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    with pytest.raises(ToolAdapterError, match="invalid_recovery_parameters"):
        adapter.execute(request(params=params))

    assert transport.calls == []


@pytest.mark.parametrize(
    "component",
    [
        "nginx.service",
        "dripvid.service",
        "postgresql.service",
        "unknown",
        "",
        123,
        None,
    ],
)
def test_unknown_or_raw_service_component_is_rejected(component):
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    with pytest.raises(ToolAdapterError, match="invalid_recovery_component"):
        adapter.execute(
            request(params={"component": component})
        )

    assert transport.calls == []


def test_recovery_requires_mutation_flag():
    transport = RecordingTransport()
    adapter = ServiceRecoverAdapter(
        targets=registry(),
        transport=transport,
    )

    with pytest.raises(ToolAdapterError, match="recovery_requires_mutation_flag"):
        adapter.execute(
            request(
                params={"component": "app"},
                mutates=False,
            )
        )

    assert transport.calls == []


def test_operational_registry_exposes_recover_as_separate_capability():
    transport = RecordingTransport()
    tools = build_operational_tool_registry(
        targets=registry(),
        transport=transport,
    )

    assert tools.resolve("service.recover") is not None
    assert tools.resolve("service.restart") is not None
    assert tools.resolve("service.recover") is not tools.resolve("service.restart")
