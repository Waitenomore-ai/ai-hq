from ai_hq.dripvid_mcp.adapter import build_dripvid_mcp_adapters
from ai_hq.missions.models import MissionRisk
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest
from ai_hq.tool_gateway.registry import ToolRegistry


class FakeMcpClient:
    def __init__(self):
        self.calls = []

    async def dripvid_health(self):
        self.calls.append(("dripvid_health", None))
        return "healthy"

    async def dripvid_git_status(self):
        self.calls.append(("dripvid_git_status", None))
        return "release"

    async def dripvid_config(self):
        self.calls.append(("dripvid_config", None))
        return "redacted"

    async def service_status(self, service):
        self.calls.append(("service_status", service))
        return f"{service}: active"


def request(capability, *, params=None, target="dripvid"):
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


def test_mcp_registry_exposes_only_four_approved_read_capabilities():
    registry = ToolRegistry(build_dripvid_mcp_adapters(FakeMcpClient()))
    approved = {
        "dripvid.health.read",
        "dripvid.release.read",
        "dripvid.config.read",
        "dripvid.service.status.read",
    }
    assert all(registry.resolve(capability) is not None for capability in approved)
    assert registry.resolve("dripvid.logs.read") is None
    assert registry.resolve("dripvid.service.restart") is None
    assert registry.resolve("mcp.tool.call") is None


def test_health_adapter_maps_to_fixed_client_method():
    client = FakeMcpClient()
    registry = ToolRegistry(build_dripvid_mcp_adapters(client))
    adapter = registry.resolve("dripvid.health.read")
    result = adapter.execute(request("dripvid.health.read"))
    assert result == {"text": "healthy"}
    assert client.calls == [("dripvid_health", None)]


def test_service_status_rejects_unapproved_service_without_other_call():
    client = FakeMcpClient()
    registry = ToolRegistry(build_dripvid_mcp_adapters(client))
    adapter = registry.resolve("dripvid.service.status.read")
    try:
        adapter.execute(
            request(
                "dripvid.service.status.read",
                params={"service": "ssh"},
            )
        )
    except ToolAdapterError:
        pass
    else:
        raise AssertionError("unapproved service must fail closed")
    assert client.calls == []


def test_mcp_adapter_rejects_unexpected_target_and_parameters():
    client = FakeMcpClient()
    registry = ToolRegistry(build_dripvid_mcp_adapters(client))
    health = registry.resolve("dripvid.health.read")

    for forged in (
        request("dripvid.health.read", target="ai-hq"),
        request("dripvid.health.read", params={"tool": "server_info"}),
    ):
        try:
            health.execute(forged)
        except ToolAdapterError:
            pass
        else:
            raise AssertionError("forged MCP request must fail closed")
    assert client.calls == []
