from typing import Protocol

from ai_hq.host_helper.client import HostHelperError
from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostCapability,
)
from ai_hq.operations.targets import OperationalTarget
from ai_hq.tool_gateway.contracts import ToolAdapterError


HOST_HELPER_MAX_LOG_LINES = 200


class HostHelperTransport(Protocol):
    def execute(self, request: HelperRequest) -> HelperResponse: ...


class HostHelperOperationalTransport:
    """Operational transport whose only privileged boundary is Host Helper."""

    def __init__(self, client: HostHelperTransport) -> None:
        self.client = client

    def _execute(self, request: HelperRequest) -> dict[str, object]:
        try:
            response = self.client.execute(request)
        except HostHelperError as exc:
            raise ToolAdapterError("host_helper_unavailable") from exc

        if not response.ok:
            raise ToolAdapterError(
                response.error or "host_helper_failed"
            )

        if (
            response.capability is not request.capability
            or response.target != request.target
        ):
            raise ToolAdapterError("host_helper_response_mismatch")

        return response.data

    def system_health(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]:
        # Host health is intentionally host-scoped. The logical operational
        # target has already been validated by the capability adapter.
        return self._execute(
            HelperRequest(
                capability=HostCapability.HOST_HEALTH,
                target=None,
                params={},
            )
        )

    def service_status(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]:
        return self._execute(
            HelperRequest(
                capability=HostCapability.SERVICE_STATUS,
                target=target.key,
                params={},
            )
        )

    def service_logs(
        self,
        target: OperationalTarget,
        *,
        lines: int,
    ) -> dict[str, object]:
        if (
            isinstance(lines, bool)
            or not isinstance(lines, int)
            or lines < 1
            or lines > HOST_HELPER_MAX_LOG_LINES
        ):
            raise ToolAdapterError("invalid_log_line_count")

        return self._execute(
            HelperRequest(
                capability=HostCapability.LOGS_RECENT,
                target=target.key,
                params={"lines": lines},
            )
        )

    def service_restart(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]:
        # Restart becomes executable only after an explicit bounded
        # Host Helper restart capability is implemented and approved.
        raise ToolAdapterError("restart_host_helper_unavailable")


# Compatibility name for code that imports the Stage 2 transport symbol.
OperationalHostTransport = HostHelperOperationalTransport
