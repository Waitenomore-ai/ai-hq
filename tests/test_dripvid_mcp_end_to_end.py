"""End-to-end DripVid MCP path over a real Unix socket.

Handover report (8 September 2026, sections 31 and 32, Priority 2): prove the
complete chat -> intent -> Tool Gateway -> MCP client -> MCP server path with
a real transport and a real MCP protocol handshake, not a fake client.

The two requests validated here are the acceptance prompts from section 32:
"Check DripVid health" and "Show me the current DripVid deployed status".
"""

import json
import socket
import stat
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_hq.agents.models import Agent
from ai_hq.chat.intents import plan_sysadmin_intent
from ai_hq.config import OperatingMode
from ai_hq.db import Base
from ai_hq.dripvid_mcp.adapter import build_dripvid_mcp_adapters
from ai_hq.dripvid_mcp.client import DripVidMcpClient
from ai_hq.dripvid_mcp.runtime import load_dripvid_mcp_token
from ai_hq.missions.models import MissionRisk
from ai_hq.missions.service import MissionService
from ai_hq.models.system_state import SystemState
from ai_hq.tool_gateway.contracts import ToolOutcomeState, ToolRequest
from ai_hq.tool_gateway.registry import ToolRegistry
from ai_hq.tool_gateway.service import ToolGateway

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="Unix-domain sockets are required for the MCP transport",
)

_PROTOCOL_VERSION = "2025-11-25"

_MCP_TOKEN = "e2e-dripvid-mcp-token"

_AGENT_PERMISSIONS = (
    "dripvid.health.read",
    "dripvid.release.read",
    "dripvid.config.read",
    "dripvid.service.status.read",
)

_TOOL_RESPONSES = {
    "dripvid_health": (
        '{"ok":true,"service":"dripvid-server-mcp","version":"0.1.0"}'
    ),
    "dripvid_git_status": (
        '{"repository":"dripvid","branch":"main",'
        '"commit":"b3ff85243c6ca60ffe3f0488ba56af62cca0fe98"}'
    ),
    "dripvid_config": '{"version":"2.84.0","secrets":"redacted"}',
}


# Unix-domain socket support is capability-guarded: the module imports and
# its tests skip cleanly on platforms without AF_UNIX (e.g. Windows).
if hasattr(socket, "AF_UNIX"):

    class _UnixHTTPServer(HTTPServer):
        address_family = socket.AF_UNIX

        def server_bind(self):
            # Bind the Unix socket path without the fqdn bookkeeping that
            # HTTPServer.server_bind performs for TCP addresses.
            super(HTTPServer, self).server_bind()


class _FakeMcpServer:
    """Minimal streamable-HTTP MCP server bound to a Unix socket."""

    def __init__(self, socket_path: str):
        self.token = _MCP_TOKEN
        self.session_id = uuid.uuid4().hex
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self._lock = threading.Lock()
        self._httpd = _UnixHTTPServer(socket_path, self._make_handler())
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.path != "/mcp":
                    self._respond(404, {"error": "not found"})
                    return

                authorization = self.headers.get("authorization", "")
                if authorization != f"Bearer {server.token}":
                    self._respond(401, {"error": "unauthorized"})
                    return

                length = int(self.headers.get("content-length", "0"))
                message = json.loads(self.rfile.read(length).decode("utf-8"))
                method = message.get("method")

                if method == "initialize":
                    self._respond(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": message.get("id"),
                            "result": {
                                "protocolVersion": _PROTOCOL_VERSION,
                                "capabilities": {},
                                "serverInfo": {
                                    "name": "dripvid-server-mcp",
                                    "version": "0.1.0",
                                },
                            },
                        },
                        session_id=server.session_id,
                    )
                    return

                if method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return

                if method == "tools/call":
                    if (
                        self.headers.get("mcp-session-id")
                        != server.session_id
                    ):
                        self._respond(440, {"error": "invalid session"})
                        return

                    params = message.get("params") or {}
                    name = params.get("name")
                    arguments = dict(params.get("arguments") or {})

                    with server._lock:
                        server.tool_calls.append(
                            (str(name), arguments)
                        )

                    if name == "service_status":
                        text = (
                            f"{arguments.get('service')}: active (running)"
                        )
                    else:
                        text = _TOOL_RESPONSES.get(str(name), "unknown tool")

                    self._respond(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": message.get("id"),
                            "result": {
                                "content": [{"type": "text", "text": text}],
                            },
                        },
                    )
                    return

                self._respond(400, {"error": "unsupported method"})

            def _respond(self, status, payload, *, session_id=None):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                if session_id is not None:
                    self.send_header("mcp-session-id", session_id)
                self.end_headers()
                self.wfile.write(body)

        return Handler



def _make_gateway(socket_path: str):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        db.add(
            SystemState(
                id=1,
                operating_mode=OperatingMode.NORMAL.value,
                simulation_mode=False,
            )
        )
        db.add(
            Agent(
                key="sysadmin",
                display_name="SysAdmin",
                role="Restricted systems operator",
                capabilities=list(_AGENT_PERMISSIONS),
                permissions=list(_AGENT_PERMISSIONS),
            )
        )
        db.commit()

    token = load_dripvid_mcp_token(_write_token_file())
    client = DripVidMcpClient(
        token=token,
        socket_path=socket_path,
        timeout_seconds=5.0,
    )
    registry = ToolRegistry(build_dripvid_mcp_adapters(client))
    gateway = ToolGateway(factory, registry=registry)
    mission = MissionService(factory).create_mission(
        title="MCP e2e",
        description="Real-socket MCP read path.",
        owner_agent="sysadmin",
        source="test",
        priority="normal",
        risk=MissionRisk.GREEN,
    )
    return gateway, mission


def _write_token_file():
    import os
    import tempfile

    handle, path = tempfile.mkstemp(prefix="dripvid-mcp-token-")
    os.write(handle, _MCP_TOKEN.encode("utf-8"))
    os.close(handle)
    os.chmod(path, stat.S_IRUSR)
    return path


def _request_from_chat_text(gateway, mission, text: str) -> ToolRequest:
    intent = plan_sysadmin_intent(text)

    assert intent.kind == "operational", intent
    assert len(intent.steps) == 1

    step = intent.steps[0]
    arguments = dict(step["tool_arguments"])

    target = str(arguments.pop("target", mission.id))
    conditions = arguments.pop("conditions", {})
    mutates_external_state = bool(
        arguments.pop("mutates_external_state", False)
    )

    return ToolRequest(
        mission_id=mission.id,
        agent_key=mission.owner_agent,
        capability=step["tool_name"],
        target=target,
        risk=mission.risk,
        params=arguments,
        conditions=conditions,
        mutates_external_state=mutates_external_state,
    )


def test_check_dripvid_health_end_to_end_over_unix_socket(tmp_path):
    server = _FakeMcpServer(str(tmp_path / "mcp.sock"))
    server.start()
    try:
        gateway, mission = _make_gateway(str(tmp_path / "mcp.sock"))

        request = _request_from_chat_text(
            gateway,
            mission,
            "Check DripVid health",
        )
        assert request.capability == "dripvid.health.read"

        outcome = gateway.execute(request)

        assert outcome.state is ToolOutcomeState.EXECUTED
        assert outcome.result == {
            "text": '{"ok":true,"service":"dripvid-server-mcp","version":"0.1.0"}'
        }
        assert server.tool_calls == [("dripvid_health", {})]
    finally:
        server.stop()


def test_dripvid_deployed_status_end_to_end_over_unix_socket(tmp_path):
    server = _FakeMcpServer(str(tmp_path / "mcp.sock"))
    server.start()
    try:
        gateway, mission = _make_gateway(str(tmp_path / "mcp.sock"))

        request = _request_from_chat_text(
            gateway,
            mission,
            "Show me the current DripVid deployed status",
        )
        assert request.capability == "dripvid.release.read"

        outcome = gateway.execute(request)

        assert outcome.state is ToolOutcomeState.EXECUTED
        assert "b3ff85243c6ca60ffe3f0488ba56af62cca0fe98" in outcome.result["text"]
        assert server.tool_calls == [("dripvid_git_status", {})]
    finally:
        server.stop()


def test_allowlisted_service_status_end_to_end_over_unix_socket(tmp_path):
    server = _FakeMcpServer(str(tmp_path / "mcp.sock"))
    server.start()
    try:
        gateway, mission = _make_gateway(str(tmp_path / "mcp.sock"))

        request = _request_from_chat_text(
            gateway,
            mission,
            "is jellyfin running on dripvid?",
        )
        assert request.capability == "dripvid.service.status.read"
        assert request.params == {"service": "jellyfin"}

        outcome = gateway.execute(request)

        assert outcome.state is ToolOutcomeState.EXECUTED
        assert outcome.result == {"text": "jellyfin: active (running)"}
        assert server.tool_calls == [
            ("service_status", {"service": "jellyfin"})
        ]
    finally:
        server.stop()


def test_unknown_service_never_reaches_the_mcp_server(tmp_path):
    server = _FakeMcpServer(str(tmp_path / "mcp.sock"))
    server.start()
    try:
        gateway, mission = _make_gateway(str(tmp_path / "mcp.sock"))

        intent = plan_sysadmin_intent("is ssh running on dripvid?")

        if intent.kind == "operational":
            for step in intent.steps:
                arguments = dict(step["tool_arguments"])
                if arguments.get("service") == "ssh":
                    pytest.fail("unknown service must not be dispatched")
                request = ToolRequest(
                    mission_id=mission.id,
                    agent_key=mission.owner_agent,
                    capability=step["tool_name"],
                    target=str(arguments.pop("target", mission.id)),
                    risk=mission.risk,
                    params=arguments,
                )
                outcome = gateway.execute(request)
                assert outcome.state is ToolOutcomeState.EXECUTED

        assert server.tool_calls == []
    finally:
        server.stop()


def test_wrong_token_is_rejected_by_the_server(tmp_path):
    server = _FakeMcpServer(str(tmp_path / "mcp.sock"))
    server.start()
    try:
        client = DripVidMcpClient(
            token="wrong-token",
            socket_path=str(tmp_path / "mcp.sock"),
            timeout_seconds=5.0,
        )
        try:
            with pytest.raises(ValueError, match="DripVid MCP request failed"):
                client.dripvid_health()
        finally:
            client.close()

        assert server.tool_calls == []
    finally:
        server.stop()
