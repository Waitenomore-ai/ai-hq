import json

import httpx
import pytest

from ai_hq.dripvid_mcp.client import DripVidMcpClient


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        return httpx.Response(
            status_code=response.get("status", 200),
            headers=response.get("headers", {"content-type": "application/json"}),
            content=json.dumps(response.get("json", {})).encode(),
            request=request,
        )


@pytest.mark.asyncio
async def test_client_initializes_then_calls_approved_tool():
    transport = RecordingTransport([
        {"json": {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "dripvid-server-mcp", "version": "0.1.0"}}}},
        {"json": {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "healthy"}]}}},
    ])
    client = DripVidMcpClient(token="secret", transport=transport)

    assert await client.dripvid_health() == "healthy"
    assert len(transport.requests) == 2
    assert transport.requests[0].url.path == "/mcp"
    assert transport.requests[0].headers["authorization"] == "Bearer secret"
    assert json.loads(transport.requests[1].content)["params"]["name"] == "dripvid_health"


@pytest.mark.asyncio
async def test_service_status_rejects_unapproved_service_before_transport():
    transport = RecordingTransport([])
    client = DripVidMcpClient(token="secret", transport=transport)
    with pytest.raises(ValueError, match="service"):
        await client.service_status("ssh")
    assert transport.requests == []


@pytest.mark.asyncio
async def test_client_rejects_malformed_tool_response():
    transport = RecordingTransport([
        {"json": {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "dripvid-server-mcp", "version": "0.1.0"}}}},
        {"json": {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "image", "data": "x"}]}}},
    ])
    client = DripVidMcpClient(token="secret", transport=transport)
    with pytest.raises(ValueError, match="response"):
        await client.dripvid_config()


def test_default_transport_is_unix_socket_only():
    client = DripVidMcpClient(
        token="secret",
        socket_path="/run/dripvid-mcp/mcp.sock",
        timeout_seconds=5.0,
    )
    assert client.socket_path == "/run/dripvid-mcp/mcp.sock"
    assert client.base_url == "http://dripvid-mcp"
