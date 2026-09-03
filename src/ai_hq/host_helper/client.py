import json
import socket

from ai_hq.host_helper.contracts import HelperRequest, HelperResponse, HostCapability

MAX_RESPONSE_BYTES = 64 * 1024


class HostHelperError(RuntimeError):
    """Bounded host-helper transport/protocol error."""


class HostHelperClient:
    def __init__(
        self,
        socket_path: str,
        credential: str,
        timeout_seconds: float = 4.0,
    ):
        self.socket_path = socket_path
        self.credential = credential
        self.timeout_seconds = timeout_seconds

    def _read_response(self, connection: socket.socket) -> bytes:
        response = bytearray()
        while len(response) <= MAX_RESPONSE_BYTES:
            chunk = connection.recv(min(4096, MAX_RESPONSE_BYTES + 1 - len(response)))
            if not chunk:
                break
            response.extend(chunk)
            if b"\n" in chunk:
                break
        if len(response) > MAX_RESPONSE_BYTES:
            raise HostHelperError("response_too_large")
        return bytes(response).split(b"\n", 1)[0]

    def execute(self, request: HelperRequest) -> HelperResponse:
        payload = {
            "credential": self.credential,
            "capability": request.capability.value,
            "target": request.target,
            "params": request.params,
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(self.socket_path)
                connection.sendall(encoded)
                raw = self._read_response(connection)
        except HostHelperError:
            raise
        except (TimeoutError, OSError):
            raise HostHelperError("connection_failed") from None

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HostHelperError("malformed_response") from None

        if not isinstance(decoded, dict):
            raise HostHelperError("malformed_response")
        if decoded.get("capability") != request.capability.value or decoded.get("target") != request.target:
            raise HostHelperError("response_mismatch")

        ok = decoded.get("ok")
        data = decoded.get("data")
        error = decoded.get("error")
        if not isinstance(ok, bool) or not isinstance(data, dict):
            raise HostHelperError("malformed_response")
        if error is not None and not isinstance(error, str):
            raise HostHelperError("malformed_response")

        try:
            capability = HostCapability(decoded["capability"])
        except (KeyError, TypeError, ValueError):
            raise HostHelperError("malformed_response") from None

        return HelperResponse(
            ok=ok,
            capability=capability,
            target=request.target,
            data=data,
            error=error,
        )
