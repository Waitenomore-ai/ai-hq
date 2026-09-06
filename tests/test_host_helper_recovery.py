from dataclasses import dataclass

import pytest

from ai_hq.host_helper import executor as executor_module
from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostAllowLists,
    HostCapability,
    validate_request,
)
from ai_hq.host_helper.executor import CompletedCommand, HostExecutor
from ai_hq.operations.targets import OperationalTarget
from ai_hq.operations.transport import HostHelperOperationalTransport


@pytest.fixture
def allow_lists() -> HostAllowLists:
    return HostAllowLists(
        services=frozenset({"ai-hq", "nginx", "dripvid"}),
        containers=frozenset({"ai-hq-web", "ai-hq-worker"}),
        logs=frozenset({"ai-hq", "nginx", "dripvid"}),
    )


def recovery_payload(component="app", *, target="dripvid", **extra_params):
    return {
        "capability": "service.recover",
        "target": target,
        "params": {
            "component": component,
            **extra_params,
        },
    }


def test_host_capability_has_distinct_service_recover_value():
    assert HostCapability.SERVICE_RECOVER.value == "service.recover"
    assert HostCapability.SERVICE_RECOVER is not HostCapability.SERVICE_RESTART


def test_contract_accepts_only_logical_dripvid_and_fixed_component(allow_lists):
    request = validate_request(recovery_payload("app"), allow_lists)

    assert request == HelperRequest(
        capability=HostCapability.SERVICE_RECOVER,
        target="dripvid",
        params={"component": "app"},
    )


@pytest.mark.parametrize("target", ["ai-hq", "nginx", "other", None])
def test_contract_rejects_non_dripvid_recovery_target(allow_lists, target):
    with pytest.raises(ValueError):
        validate_request(
            recovery_payload("app", target=target),
            allow_lists,
        )


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
def test_contract_rejects_raw_or_unknown_component(allow_lists, component):
    with pytest.raises(ValueError, match="component"):
        validate_request(
            recovery_payload(component),
            allow_lists,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "capability": "service.recover",
            "target": "dripvid",
            "params": {},
        },
        recovery_payload("app", unit="nginx.service"),
        recovery_payload("app", command="systemctl restart nginx"),
        recovery_payload("app", path="/tmp/x"),
        recovery_payload("app", host="other-host"),
    ],
)
def test_contract_rejects_missing_or_extra_recovery_parameters(
    allow_lists,
    payload,
):
    with pytest.raises(ValueError):
        validate_request(payload, allow_lists)


def test_executor_owns_exact_fixed_component_to_unit_mapping():
    assert executor_module.RECOVERY_SERVICE_UNITS == {
        "app": "dripvid.service",
        "mcp": "dripvid-mcp.service",
        "proxy": "nginx.service",
        "tunnel": "cloudflared.service",
        "database": "postgresql.service",
    }


class RecordingRunner:
    def __init__(self, component):
        unit = {
            "app": "dripvid.service",
            "mcp": "dripvid-mcp.service",
            "proxy": "nginx.service",
            "tunnel": "cloudflared.service",
            "database": "postgresql.service",
        }[component]
        self.calls = []
        self.responses = {
            ("systemctl", "restart", unit): CompletedCommand(0, "", ""),
            (
                "systemctl",
                "show",
                unit,
                "--no-page",
                "--property=ActiveState,SubState,LoadState,UnitFileState",
            ): CompletedCommand(
                0,
                "ActiveState=active\nSubState=running\nLoadState=loaded\n",
                "",
            ),
        }

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        return self.responses[tuple(argv)]


@pytest.mark.parametrize(
    "component",
    ["app", "mcp", "proxy", "tunnel", "database"],
)
def test_executor_uses_only_fixed_systemctl_restart_and_show(
    allow_lists,
    component,
):
    runner = RecordingRunner(component)
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.SERVICE_RECOVER,
            target="dripvid",
            params={"component": component},
        )
    )

    unit = executor_module.RECOVERY_SERVICE_UNITS[component]

    assert response.ok is True
    assert response.target == "dripvid"
    assert response.data["component"] == component
    assert response.data["restarted"] is True
    assert response.data["active_state"] == "active"
    assert [call[0] for call in runner.calls] == [
        ["systemctl", "restart", unit],
        [
            "systemctl",
            "show",
            unit,
            "--no-page",
            "--property=ActiveState,SubState,LoadState,UnitFileState",
        ],
    ]


def test_executor_revalidates_component_even_for_manually_built_request(allow_lists):
    runner = RecordingRunner("app")
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.SERVICE_RECOVER,
            target="dripvid",
            params={"component": "nginx.service"},
        )
    )

    assert response.ok is False
    assert response.error == "invalid parameters"
    assert runner.calls == []


@dataclass
class RecordingClient:
    requests: list[HelperRequest]

    def execute(self, request):
        self.requests.append(request)
        return HelperResponse(
            ok=True,
            capability=request.capability,
            target=request.target,
            data={"restarted": True, "component": request.params["component"]},
        )


def test_operational_transport_converts_component_to_exact_helper_request():
    client = RecordingClient(requests=[])
    transport = HostHelperOperationalTransport(client)
    target = OperationalTarget(
        key="dripvid",
        service_unit="dripvid.service",
        allowed_capabilities=frozenset({"service.recover"}),
    )

    result = transport.service_recover(target, component="proxy")

    assert result == {"restarted": True, "component": "proxy"}
    assert client.requests == [
        HelperRequest(
            capability=HostCapability.SERVICE_RECOVER,
            target="dripvid",
            params={"component": "proxy"},
        )
    ]
