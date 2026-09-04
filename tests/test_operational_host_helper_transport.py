from dataclasses import dataclass, field

import pytest

from ai_hq.host_helper.contracts import HelperRequest, HelperResponse, HostCapability
from ai_hq.operations.targets import OperationalTarget
from ai_hq.operations.transport import HostHelperOperationalTransport
from ai_hq.tool_gateway.contracts import ToolAdapterError


@dataclass
class FakeHostHelper:
    requests: list[HelperRequest] = field(default_factory=list)
    responses: dict[HostCapability, dict[str, object]] = field(
        default_factory=lambda: {
            HostCapability.HOST_HEALTH: {"status": "ok"},
            HostCapability.SERVICE_STATUS: {"active_state": "active"},
            HostCapability.LOGS_RECENT: {"text": "hello"},
        }
    )

    def execute(self, request: HelperRequest) -> HelperResponse:
        self.requests.append(request)
        return HelperResponse(
            ok=True,
            capability=request.capability,
            target=request.target,
            data=self.responses.get(request.capability, {}),
        )


def target() -> OperationalTarget:
    return OperationalTarget(
        key="dripvid",
        service_unit="dripvid.service",
        log_unit="dripvid",
        allowed_capabilities=frozenset(
            {
                "system.health.read",
                "service.status.read",
                "service.logs.read",
                "service.restart",
            }
        ),
    )


def test_health_routes_through_host_helper():
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    result = transport.system_health(target())

    assert result == {"status": "ok"}
    assert helper.requests == [
        HelperRequest(
            capability=HostCapability.HOST_HEALTH,
            target=None,
            params={},
        )
    ]


def test_status_uses_logical_target_not_service_unit():
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    result = transport.service_status(target())

    assert result == {"active_state": "active"}
    assert helper.requests[0].capability is HostCapability.SERVICE_STATUS
    assert helper.requests[0].target == "dripvid"
    assert "dripvid.service" not in repr(helper.requests[0])


def test_logs_are_bounded_before_host_helper():
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    transport.service_logs(target(), lines=500)

    assert helper.requests[0] == HelperRequest(
        capability=HostCapability.LOGS_RECENT,
        target="dripvid",
        params={"lines": 500},
    )

    with pytest.raises(ToolAdapterError, match="invalid_log_line_count"):
        transport.service_logs(target(), lines=501)

    assert len(helper.requests) == 1


def test_restart_routes_through_host_helper_with_logical_target():
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)
    target = OperationalTarget(
        key="dripvid",
        service_unit="dripvid.service",
        allowed_capabilities=frozenset({"service.restart"}),
    )

    result = transport.service_restart(target)

    assert result == {}
    assert len(helper.requests) == 1

    request = helper.requests[0]
    assert request.capability is HostCapability.SERVICE_RESTART
    assert request.target == target.key
    assert request.params == {}
def test_operational_transport_contains_no_subprocess_execution():
    import inspect
    import ai_hq.operations.transport as module

    source = inspect.getsource(module)

    assert "subprocess" not in source
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "os.popen" not in source
