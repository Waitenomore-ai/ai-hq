from __future__ import annotations

import json
from collections.abc import Mapping

import httpx

_PROTOCOL_VERSION = "2025-11-25"
_ALLOWED_SERVICES = frozenset({"dripvid", "jellyfin", "cloudflared", "dripvid-requests"})
_MAX_RESPONSE_BYTES = 256 * 1024


class DripVidMcpClient:
    def __init__(
        self,
        *,
        token: str,
        socket_path: str = "/run/dripvid-mcp/mcp.sock",
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token or any(character.isspace() for character in token):
            raise ValueError("DripVid MCP token is invalid")
        if not socket_path.startswith("/") or "://" in socket_path:
            raise ValueError("DripVid MCP socket path is invalid")
        if timeout_seconds < 0.5 or timeout_seconds > 30.0:
            raise ValueError("DripVid MCP timeout is outside the allowed range")

        self.socket_path = socket_path
        self.base_url = "http://localhost"
        self._token = token
        self._session_id: str | None = None
        self._initialized = False
        self._next_id = 1
        if transport is None:
            transport = httpx.HTTPTransport(uds=socket_path)
        self._client = httpx.Client(
            transport=transport,
            base_url=self.base_url,
            timeout=timeout_seconds,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def dripvid_health(self) -> str:
        return self._call_tool("dripvid_health", {})

    def dripvid_git_status(self) -> str:
        return self._call_tool("dripvid_git_status", {})

    def dripvid_config(self) -> str:
        return self._call_tool("dripvid_config", {})

    def service_status(self, service: str) -> str:
        if service not in _ALLOWED_SERVICES:
            raise ValueError("DripVid MCP service is not allowlisted")
        return self._call_tool("service_status", {"service": service})

    def _initialize(self) -> None:
        if self._initialized:
            return
        request_id = self._allocate_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ai-hq", "version": "0.1.0"},
            },
        }
        result, headers = self._post_rpc(
            payload,
            request_id=request_id,
            initialized=False,
        )
        if not isinstance(result, Mapping):
            raise ValueError("DripVid MCP initialization response is invalid")
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or protocol_version != _PROTOCOL_VERSION:
            raise ValueError("DripVid MCP initialization response is invalid")
        session_id = headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        self._send_initialized_notification()
        self._initialized = True

    def _send_initialized_notification(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        response = self._post(
            payload,
            initialized=True,
        )
        if 300 <= response.status_code < 400:
            raise ValueError("DripVid MCP redirects are not allowed")
        if response.status_code not in {200, 202, 204}:
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ValueError("DripVid MCP initialization notification failed") from exc
            raise ValueError("DripVid MCP initialization notification failed")

    def _call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self._initialize()
        request_id = self._allocate_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        result, _headers = self._post_rpc(
            payload,
            request_id=request_id,
            initialized=True,
        )
        if not isinstance(result, Mapping):
            raise ValueError("DripVid MCP tool response is invalid")
        if result.get("isError") is True:
            raise ValueError("DripVid MCP tool returned an error")
        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise ValueError("DripVid MCP tool response is invalid")
        item = content[0]
        if not isinstance(item, Mapping) or item.get("type") != "text":
            raise ValueError("DripVid MCP tool response is invalid")
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("DripVid MCP tool response is invalid")
        return text

    def _allocate_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _headers(self, *, initialized: bool) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self._token}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if initialized:
            headers["mcp-protocol-version"] = _PROTOCOL_VERSION
            if self._session_id:
                headers["mcp-session-id"] = self._session_id
        return headers

    def _post(
        self,
        payload: dict[str, object],
        *,
        initialized: bool,
    ) -> httpx.Response:
        try:
            return self._client.post(
                "/mcp",
                headers=self._headers(initialized=initialized),
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ValueError("DripVid MCP transport failed") from exc

    def _post_rpc(
        self,
        payload: dict[str, object],
        *,
        request_id: int,
        initialized: bool,
    ) -> tuple[object, httpx.Headers]:
        response = self._post(payload, initialized=initialized)
        if 300 <= response.status_code < 400:
            raise ValueError("DripVid MCP redirects are not allowed")
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError("DripVid MCP request failed") from exc

        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                parsed_length = int(content_length)
            except ValueError as exc:
                raise ValueError("DripVid MCP response length is invalid") from exc
            if parsed_length > _MAX_RESPONSE_BYTES:
                raise ValueError("DripVid MCP response is too large")
        body = response.content
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("DripVid MCP response is too large")

        message = self._decode_rpc_message(response, body, request_id=request_id)
        if message.get("jsonrpc") != "2.0" or message.get("id") != request_id:
            raise ValueError("DripVid MCP response is invalid")
        if "error" in message:
            raise ValueError("DripVid MCP request failed")
        if "result" not in message:
            raise ValueError("DripVid MCP response is invalid")
        return message["result"], response.headers

    @staticmethod
    def _decode_rpc_message(
        response: httpx.Response,
        body: bytes,
        *,
        request_id: int,
    ) -> dict[str, object]:
        content_type = response.headers.get("content-type", "").casefold()
        candidates: list[object] = []
        try:
            if "text/event-stream" in content_type:
                text = body.decode("utf-8")
                for line in text.splitlines():
                    if not line.startswith("data:"):
                        continue
                    candidates.append(json.loads(line[5:].strip()))
            else:
                candidates.append(json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("DripVid MCP response is malformed") from exc

        for candidate in reversed(candidates):
            if isinstance(candidate, dict) and candidate.get("id") == request_id:
                return candidate
        raise ValueError("DripVid MCP response is invalid")
