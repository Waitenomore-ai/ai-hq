import json

import httpx
import pytest

from ai_hq.dripvid_mcp.client import DripVidMcpClient


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if "content" in response:
            content = response["content"]
        else:
            content = json.dumps(response.get("json", {})).encode()
        return httpx.Response(
            status_code=response.get("status", 200),
            headers=response.get("headers", {"content-type": "application/json"}),
            content=content,
            request=request,
        )


def initialization_response():
    return {
        "headers": {
            "content-type": "application/json",
            "mcp-session-id": "session-1",
        },
        "json": {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "serverInfo": {"name": "dripvid-server-mcp", "version": "0.1.0"},
            },
        },
    }


def test_client_initializes_notifies_then_calls_approved_tool_synchronously():
    transport = RecordingTransport([
        initialization_response(),
        {"status": 202, "content": b""},
        {"json": {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "healthy"}]}}},
    ])
    client = DripVidMcpClient(token="secret", transport=transport)

    assert client.dripvid_health() == "healthy"
    assert len(transport.requests) == 3
    assert transport.requests[0].url.path == "/mcp"
    assert transport.requests[0].url.host == "localhost"
    assert transport.requests[0].headers["authorization"] == "Bearer secret"

    initialized = json.loads(transport.requests[1].content)
    assert initialized == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert transport.requests[1].headers["mcp-session-id"] == "session-1"

    tool_call = json.loads(transport.requests[2].content)
    assert tool_call["params"]["name"] == "dripvid_health"
    assert transport.requests[2].headers["mcp-session-id"] == "session-1"


def test_service_status_rejects_unapproved_service_before_transport():
    transport = RecordingTransport([])
    client = DripVidMcpClient(token="secret", transport=transport)
    with pytest.raises(ValueError, match="service"):
        client.service_status("ssh")
    assert transport.requests == []


def test_client_rejects_malformed_tool_response():
    transport = RecordingTransport([
        initialization_response(),
        {"status": 202, "content": b""},
        {"json": {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "image", "data": "x"}]}}},
    ])
    client = DripVidMcpClient(token="secret", transport=transport)
    with pytest.raises(ValueError, match="response"):
        client.dripvid_config()


def test_same_client_can_execute_multiple_calls_without_event_loop_handoffs():
    transport = RecordingTransport([
        initialization_response(),
        {"status": 202, "content": b""},
        {"json": {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "healthy"}]}}},
        {"json": {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "release"}]}}},
    ])
    client = DripVidMcpClient(token="secret", transport=transport)

    assert client.dripvid_health() == "healthy"
    assert client.dripvid_git_status() == "release"
    assert len(transport.requests) == 4


def test_default_transport_is_unix_socket_only_with_allowed_host_header():
    client = DripVidMcpClient(
        token="secret",
        socket_path="/run/dripvid-mcp/mcp.sock",
        timeout_seconds=5.0,
    )
    assert client.socket_path == "/run/dripvid-mcp/mcp.sock"
    assert client.base_url == "http://localhost"
