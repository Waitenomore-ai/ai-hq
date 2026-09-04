from typing import Protocol

from ai_hq.host_helper.client import HostHelperError
from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostAllowLists,
    HostCapability,
    validate_request,
)
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest


class HostHelperTransport(Protocol):
    def execute(self, request: HelperRequest) -> HelperResponse: ...


class HostHelperAdapter:
    def __init__(
        self,
        *,
        capability: str,
        client: HostHelperTransport,
        allow_lists: HostAllowLists,
    ) -> None:
        try:
            self.host_capability = HostCapability(capability)
        except ValueError as exc:
            raise ValueError("unsupported host capability") from exc

        read_only_capabilities = {
            HostCapability.HOST_HEALTH,
            HostCapability.HOST_RESOURCES,
            HostCapability.SERVICE_STATUS,
            HostCapability.CONTAINER_STATUS,
            HostCapability.LOGS_RECENT,
        }

        if self.host_capability not in read_only_capabilities:
            raise ValueError("unsupported host capability")

        self.capability = self.host_capability.value
        self.client = client
        self.allow_lists = allow_lists

    def execute(self, request: ToolRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "capability": self.capability,
            "params": request.params,
        }
        if self.host_capability not in {
            HostCapability.HOST_HEALTH,
            HostCapability.HOST_RESOURCES,
        }:
            payload["target"] = request.target

        try:
            helper_request = validate_request(payload, self.allow_lists)
        except (TypeError, ValueError):
            raise ToolAdapterError("invalid_host_request") from None

        try:
            response = self.client.execute(helper_request)
        except HostHelperError as exc:
            raise ToolAdapterError("host_helper_unavailable") from exc

        if not response.ok:
            raise ToolAdapterError(response.error or "host_helper_failed")
        return response.data
