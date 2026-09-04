from dataclasses import dataclass, field

import pytest

from ai_hq.host_helper.client import HostHelperError
from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostCapability,
)
from ai_hq.operations.targets import OperationalTarget
from ai_hq.operations.transport import HostHelperOperationalTransport
from ai_hq.tool_gateway.contracts import ToolAdapterError


@dataclass
class FakeHostHelper:
    requests: list[HelperRequest] = field(default_factory=list)
    fail: bool = False
    helper_error: bool = False

    def execute(self, request: HelperRequest) -> HelperResponse:
        self.requests.append(request)

        if self.helper_error:
            raise HostHelperError("connection_failed")

        if self.fail:
            return HelperResponse(
                ok=False,
                capability=request.capability,
                target=request.target,
                data={},
                error="command_failed",
            )

        data: dict[str, object]

        if request.capability is HostCapability.HOST_HEALTH:
            data = {"status": "ok"}
        elif request.capability is HostCapability.SERVICE_STATUS:
            data = {
                "active_state": "active",
                "sub_state": "running",
            }
        elif request.capability is HostCapability.LOGS_RECENT:
            data = {
                "text": "bounded log output",
                "lines_requested": request.params["lines"],
                "truncated": False,
            }
        else:
            data = {}

        return HelperResponse(
            ok=True,
            capability=request.capability,
            target=request.target,
            data=data,
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


def test_system_health_uses_host_helper():
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    assert transport.system_health(target()) == {"status": "ok"}

    assert helper.requests == [
        HelperRequest(
            capability=HostCapability.HOST_HEALTH,
            target=None,
            params={},
        )
    ]


def test_service_status_uses_trusted_logical_target():
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    result = transport.service_status(target())

    assert result["active_state"] == "active"
    assert helper.requests == [
        HelperRequest(
            capability=HostCapability.SERVICE_STATUS,
            target="dripvid",
            params={},
        )
    ]


@pytest.mark.parametrize("lines", [1, 100, 500])
def test_logs_accept_host_helper_bounded_line_counts(lines):
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    result = transport.service_logs(target(), lines=lines)

    assert result["lines_requested"] == lines
    assert helper.requests[-1] == HelperRequest(
        capability=HostCapability.LOGS_RECENT,
        target="dripvid",
        params={"lines": lines},
    )


@pytest.mark.parametrize("lines", [0, 501, -1, True, "100"])
def test_logs_reject_values_outside_host_helper_contract(lines):
    helper = FakeHostHelper()
    transport = HostHelperOperationalTransport(helper)

    with pytest.raises(ToolAdapterError, match="invalid_log_line_count"):
        transport.service_logs(target(), lines=lines)

    assert helper.requests == []


def test_host_helper_failure_fails_closed():
    helper = FakeHostHelper(fail=True)
    transport = HostHelperOperationalTransport(helper)

    with pytest.raises(ToolAdapterError, match="command_failed"):
        transport.service_status(target())


def test_host_helper_connection_failure_fails_closed():
    helper = FakeHostHelper(helper_error=True)
    transport = HostHelperOperationalTransport(helper)

    with pytest.raises(ToolAdapterError, match="host_helper_unavailable"):
        transport.service_status(target())


def test_restart_routes_only_through_host_helper():
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
    assert helper.requests[0].capability is HostCapability.SERVICE_RESTART
    assert helper.requests[0].target == "dripvid"
    assert helper.requests[0].params == {}
