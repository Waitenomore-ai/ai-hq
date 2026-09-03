import json
import socket
import threading
from pathlib import Path

import pytest

from ai_hq.host_helper.client import MAX_RESPONSE_BYTES, HostHelperClient, HostHelperError
from ai_hq.host_helper.contracts import HelperRequest, HostCapability


def run_server(socket_path: Path, response: bytes, seen: list[dict]) -> threading.Thread:
    def serve():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            server.listen(1)
            connection, _ = server.accept()
            with connection:
                request = b""
                while not request.endswith(b"\n"):
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    request += chunk
                seen.append(json.loads(request))
                connection.sendall(response)

    thread = threading.Thread(target=serve)
    thread.start()
    for _ in range(100):
        if socket_path.exists():
            break
        threading.Event().wait(0.01)
    return thread


def test_client_sends_authenticated_request_and_returns_response(tmp_path: Path):
    socket_path = tmp_path / "helper.sock"
    seen: list[dict] = []
    thread = run_server(
        socket_path,
        b'{"ok":true,"capability":"host.health","target":null,"data":{"status":"ok"},"error":null}\n',
        seen,
    )
    client = HostHelperClient(str(socket_path), "service-secret")

    response = client.execute(HelperRequest(HostCapability.HOST_HEALTH, None, {}))
    thread.join(timeout=2)

    assert response.ok is True
    assert response.data == {"status": "ok"}
    assert seen[0]["credential"] == "service-secret"
    assert seen[0]["capability"] == "host.health"


def test_client_normalizes_connect_failure_without_leaking_credential(tmp_path: Path):
    credential = "never-show-this-secret"
    client = HostHelperClient(str(tmp_path / "missing.sock"), credential, timeout_seconds=0.1)

    with pytest.raises(HostHelperError, match="connection_failed") as exc_info:
        client.execute(HelperRequest(HostCapability.HOST_HEALTH, None, {}))

    assert credential not in str(exc_info.value)


def test_client_rejects_malformed_response(tmp_path: Path):
    socket_path = tmp_path / "helper.sock"
    thread = run_server(socket_path, b"not-json\n", [])
    client = HostHelperClient(str(socket_path), "secret")

    with pytest.raises(HostHelperError, match="malformed_response"):
        client.execute(HelperRequest(HostCapability.HOST_HEALTH, None, {}))
    thread.join(timeout=2)


def test_client_rejects_oversized_response(tmp_path: Path):
    socket_path = tmp_path / "helper.sock"
    thread = run_server(socket_path, b"x" * (MAX_RESPONSE_BYTES + 1), [])
    client = HostHelperClient(str(socket_path), "secret")

    with pytest.raises(HostHelperError, match="response_too_large"):
        client.execute(HelperRequest(HostCapability.HOST_HEALTH, None, {}))
    thread.join(timeout=2)


def test_client_rejects_capability_or_target_echo_mismatch(tmp_path: Path):
    socket_path = tmp_path / "helper.sock"
    thread = run_server(
        socket_path,
        b'{"ok":true,"capability":"host.resources","target":null,"data":{},"error":null}\n',
        [],
    )
    client = HostHelperClient(str(socket_path), "secret")

    with pytest.raises(HostHelperError, match="response_mismatch"):
        client.execute(HelperRequest(HostCapability.HOST_HEALTH, None, {}))
    thread.join(timeout=2)
