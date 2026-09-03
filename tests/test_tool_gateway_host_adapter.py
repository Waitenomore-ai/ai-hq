import pytest

from ai_hq.host_helper.contracts import HelperResponse, HostAllowLists, HostCapability
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest
from ai_hq.tool_gateway.host_adapter import HostHelperAdapter
from ai_hq.missions.models import MissionRisk


class FakeHostClient:
    def __init__(self, response: HelperResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def gateway_request(capability: str, *, target="ai-hq", params=None):
    return ToolRequest(
        mission_id="mission-1",
        agent_key="sysadmin",
        capability=capability,
        target=target,
        risk=MissionRisk.GREEN,
        params=params or {},
        conditions={},
        mutates_external_state=False,
    )


def allow_lists():
    return HostAllowLists(
        services=frozenset({"ai-hq"}),
        containers=frozenset({"ai-hq-web"}),
        logs=frozenset({"ai-hq"}),
    )


def test_host_adapter_supports_only_existing_read_only_host_capabilities():
    supported = {item.value for item in HostCapability}
    assert supported == {
        "host.health",
        "host.resources",
        "service.status",
        "container.status",
        "logs.recent",
    }

    for capability in supported:
        adapter = HostHelperAdapter(
            capability=capability,
            client=FakeHostClient(),
            allow_lists=allow_lists(),
        )
        assert adapter.capability == capability

    with pytest.raises(ValueError, match="unsupported host capability"):
        HostHelperAdapter(
            capability="shell.execute",
            client=FakeHostClient(),
            allow_lists=allow_lists(),
        )


def test_host_health_translation_drops_gateway_target_and_uses_strict_helper_contract():
    client = FakeHostClient(
        HelperResponse(
            ok=True,
            capability=HostCapability.HOST_HEALTH,
            target=None,
            data={"status": "ok"},
        )
    )
    adapter = HostHelperAdapter(
        capability="host.health", client=client, allow_lists=allow_lists()
    )

    result = adapter.execute(gateway_request("host.health"))

    assert result == {"status": "ok"}
    assert client.requests[0].capability is HostCapability.HOST_HEALTH
    assert client.requests[0].target is None
    assert client.requests[0].params == {}


def test_targeted_host_request_uses_existing_allowlist_validation():
    client = FakeHostClient(
        HelperResponse(
            ok=True,
            capability=HostCapability.SERVICE_STATUS,
            target="ai-hq",
            data={"active": True},
        )
    )
    adapter = HostHelperAdapter(
        capability="service.status", client=client, allow_lists=allow_lists()
    )

    assert adapter.execute(gateway_request("service.status")) == {"active": True}

    with pytest.raises(ToolAdapterError, match="invalid_host_request"):
        adapter.execute(gateway_request("service.status", target="dripvid"))


def test_failed_host_response_becomes_explicit_adapter_error():
    client = FakeHostClient(
        HelperResponse(
            ok=False,
            capability=HostCapability.LOGS_RECENT,
            target="ai-hq",
            data={},
            error="helper_failed",
        )
    )
    adapter = HostHelperAdapter(
        capability="logs.recent", client=client, allow_lists=allow_lists()
    )

    with pytest.raises(ToolAdapterError, match="helper_failed"):
        adapter.execute(gateway_request("logs.recent", params={"lines": 20}))
