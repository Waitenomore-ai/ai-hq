from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ai_hq.dripvid_mcp.client import DripVidMcpClient
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest

_ALLOWED_SERVICES = frozenset({"dripvid", "jellyfin", "cloudflared", "dripvid-requests"})


class DripVidMcpAdapter:
    def __init__(self, *, capability: str, client: DripVidMcpClient) -> None:
        self.capability = capability
        self._client = client

    def execute(self, request: ToolRequest) -> dict[str, object]:
        if request.target != "dripvid":
            raise ToolAdapterError("invalid_target")

        try:
            operation = self._operation(request)
            text = asyncio.run(operation())
        except ToolAdapterError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolAdapterError("dripvid_mcp_failed") from exc
        return {"text": text}

    def _operation(self, request: ToolRequest) -> Callable[[], Awaitable[str]]:
        if self.capability == "dripvid.health.read":
            self._require_no_params(request)
            return self._client.dripvid_health
        if self.capability == "dripvid.release.read":
            self._require_no_params(request)
            return self._client.dripvid_git_status
        if self.capability == "dripvid.config.read":
            self._require_no_params(request)
            return self._client.dripvid_config
        if self.capability == "dripvid.service.status.read":
            if set(request.params) != {"service"}:
                raise ToolAdapterError("invalid_params")
            service = request.params.get("service")
            if not isinstance(service, str) or service not in _ALLOWED_SERVICES:
                raise ToolAdapterError("invalid_service")
            return lambda: self._client.service_status(service)
        raise ToolAdapterError("invalid_capability")

    @staticmethod
    def _require_no_params(request: ToolRequest) -> None:
        if request.params:
            raise ToolAdapterError("invalid_params")


def build_dripvid_mcp_adapters(client: DripVidMcpClient) -> tuple[DripVidMcpAdapter, ...]:
    return tuple(
        DripVidMcpAdapter(capability=capability, client=client)
        for capability in (
            "dripvid.health.read",
            "dripvid.release.read",
            "dripvid.config.read",
            "dripvid.service.status.read",
        )
    )
