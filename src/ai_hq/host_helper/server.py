import hmac
import json
import os
import socket
import stat
from pathlib import Path
from typing import Protocol

from ai_hq.host_helper.contracts import HelperResponse, HostAllowLists, validate_request
from ai_hq.host_helper.executor import HostExecutor

MAX_REQUEST_BYTES = 16 * 1024
DEFAULT_SOCKET_PATH = "/run/ai-hq/host-helper.sock"


class Executor(Protocol):
    def execute(self, request): ...


def _error(error: str) -> dict[str, object]:
    return {"ok": False, "capability": None, "target": None, "data": {}, "error": error}


def _response_dict(response: HelperResponse) -> dict[str, object]:
    return {
        "ok": response.ok,
        "capability": response.capability.value,
        "target": response.target,
        "data": response.data,
        "error": response.error,
    }


class HostHelperServer:
    def __init__(
        self,
        socket_path: str | Path,
        credential: str,
        allow_lists: HostAllowLists,
        executor: Executor,
    ):
        self.socket_path = Path(socket_path)
        self.credential = credential
        self.allow_lists = allow_lists
        self.executor = executor
        self._socket: socket.socket | None = None

    def bind(self) -> None:
        if self._socket is not None:
            raise RuntimeError("server already bound")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            mode = self.socket_path.lstat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError("existing socket path is not a socket")
            self.socket_path.unlink()

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o660)
            listener.listen(8)
        except Exception:
            listener.close()
            if self.socket_path.exists() and stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                self.socket_path.unlink()
            raise
        self._socket = listener

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self.socket_path.exists() and stat.S_ISSOCK(self.socket_path.lstat().st_mode):
            self.socket_path.unlink()

    def _read_request(self, connection: socket.socket) -> bytes:
        data = bytearray()
        while len(data) <= MAX_REQUEST_BYTES:
            chunk = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if b"\n" in chunk:
                break
        return bytes(data)

    def _handle_payload(self, raw: bytes) -> dict[str, object]:
        if len(raw) > MAX_REQUEST_BYTES:
            return _error("request too large")
        line = raw.split(b"\n", 1)[0]
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error("invalid request")
        if not isinstance(payload, dict):
            return _error("invalid request")

        supplied = payload.pop("credential", None)
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.credential):
            return _error("authentication failed")

        try:
            request = validate_request(payload, self.allow_lists)
        except (TypeError, ValueError):
            return _error("invalid request")
        return _response_dict(self.executor.execute(request))

    def serve_once(self) -> None:
        if self._socket is None:
            raise RuntimeError("server is not bound")
        connection, _ = self._socket.accept()
        with connection:
            response = self._handle_payload(self._read_request(connection))
            connection.sendall(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")

    def serve_forever(self) -> None:
        if self._socket is None:
            self.bind()
        while True:
            self.serve_once()


def _default_allow_lists() -> HostAllowLists:
    return HostAllowLists(
        services=frozenset({"ai-hq", "nginx", "dripvid"}),
        containers=frozenset({"ai-hq-web", "ai-hq-worker", "dripvid"}),
        logs=frozenset({"ai-hq", "nginx", "dripvid"}),
    )


def main() -> int:
    credential = os.environ.get("AI_HQ_HOST_HELPER_CREDENTIAL")
    if not credential:
        raise SystemExit("AI_HQ_HOST_HELPER_CREDENTIAL is required")
    socket_path = os.environ.get("AI_HQ_HOST_HELPER_SOCKET", DEFAULT_SOCKET_PATH)
    allow_lists = _default_allow_lists()
    server = HostHelperServer(socket_path, credential, allow_lists, HostExecutor(allow_lists))
    server.bind()
    try:
        server.serve_forever()
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
