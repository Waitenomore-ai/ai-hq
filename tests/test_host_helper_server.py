import json
import socket
import stat
import threading
from pathlib import Path

import pytest

from ai_hq.host_helper.contracts import HelperResponse, HostAllowLists
from ai_hq.host_helper.server import MAX_REQUEST_BYTES, HostHelperServer, _default_allow_lists


class FakeExecutor:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return HelperResponse(True, request.capability, request.target, {"status": "ok"})


@pytest.fixture
def allow_lists() -> HostAllowLists:
    return HostAllowLists(
        services=frozenset({"ai-hq", "nginx", "dripvid"}),
        containers=frozenset({"ai-hq-web", "ai-hq-worker"}),
        logs=frozenset({"ai-hq", "nginx", "dripvid"}),
    )


def exchange(server: HostHelperServer, payload: bytes) -> dict:
    thread = threading.Thread(target=server.serve_once)
    thread.start()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(server.socket_path))
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        response = b""
        while not response.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
    thread.join(timeout=2)
    assert not thread.is_alive()
    return json.loads(response)


def test_default_allow_lists_match_live_host_topology():
    allow_lists = _default_allow_lists()

    assert "dripvid" in allow_lists.services
    assert "dripvid" in allow_lists.logs
    assert "dripvid" not in allow_lists.containers
    assert allow_lists.containers == frozenset({"ai-hq-web", "ai-hq-worker"})


def test_missing_and_invalid_credentials_have_same_failure(
    tmp_path: Path,
    allow_lists: HostAllowLists,
):
    executor = FakeExecutor()
    server = HostHelperServer(tmp_path / "helper.sock", "correct-secret", allow_lists, executor)
    server.bind()
    try:
        missing = exchange(
            server,
            b'{"capability":"host.health","target":null,"params":{}}\n',
        )
        invalid = exchange(
            server,
            b'{"credential":"wrong","capability":"host.health","target":null,"params":{}}\n',
        )
    finally:
        server.close()

    assert missing["ok"] is False
    assert invalid["ok"] is False
    assert missing["error"] == invalid["error"] == "authentication failed"
    assert executor.requests == []


def test_valid_request_invokes_executor_once(tmp_path: Path, allow_lists: HostAllowLists):
    executor = FakeExecutor()
    server = HostHelperServer(tmp_path / "helper.sock", "correct-secret", allow_lists, executor)
    server.bind()
    try:
        response = exchange(
            server,
            b'{"credential":"correct-secret","capability":"host.health","target":null,"params":{}}\n',
        )
    finally:
        server.close()

    assert response["ok"] is True
    assert response["capability"] == "host.health"
    assert len(executor.requests) == 1


def test_invalid_json_returns_bounded_error(tmp_path: Path, allow_lists: HostAllowLists):
    executor = FakeExecutor()
    server = HostHelperServer(tmp_path / "helper.sock", "secret", allow_lists, executor)
    server.bind()
    try:
        response = exchange(server, b"not-json\n")
    finally:
        server.close()

    assert response["ok"] is False
    assert response["error"] == "invalid request"


def test_oversized_request_is_rejected(tmp_path: Path, allow_lists: HostAllowLists):
    executor = FakeExecutor()
    server = HostHelperServer(tmp_path / "helper.sock", "secret", allow_lists, executor)
    server.bind()
    try:
        response = exchange(server, b"x" * (MAX_REQUEST_BYTES + 1))
    finally:
        server.close()

    assert response["ok"] is False
    assert response["error"] == "request too large"
    assert executor.requests == []


def test_socket_mode_is_0660(tmp_path: Path, allow_lists: HostAllowLists):
    server = HostHelperServer(tmp_path / "helper.sock", "secret", allow_lists, FakeExecutor())
    server.bind()
    try:
        mode = stat.S_IMODE(server.socket_path.stat().st_mode)
    finally:
        server.close()
    assert mode == 0o660


def test_bind_removes_stale_socket_but_refuses_non_socket(
    tmp_path: Path,
    allow_lists: HostAllowLists,
):
    socket_path = tmp_path / "helper.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()

    server = HostHelperServer(socket_path, "secret", allow_lists, FakeExecutor())
    server.bind()
    server.close()

    socket_path.write_text("do not delete")
    refusing = HostHelperServer(socket_path, "secret", allow_lists, FakeExecutor())
    with pytest.raises(RuntimeError, match="not a socket"):
        refusing.bind()
    assert socket_path.read_text() == "do not delete"
