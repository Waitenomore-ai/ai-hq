from typing import Protocol

from ai_hq.host_helper.client import HostHelperError
from ai_hq.host_helper.contracts import (
    HelperRequest,
    HelperResponse,
    HostCapability,
)
from ai_hq.operations.targets import OperationalTarget
from ai_hq.tool_gateway.contracts import ToolAdapterError


HOST_HELPER_MAX_LOG_LINES = 500


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
            raise ToolAdapterError(response.error or "host_helper_failed")
        if response.capability is not request.capability or response.target != request.target:
            raise ToolAdapterError("host_helper_response_mismatch")
        return response.data

    def system_health(self, target: OperationalTarget) -> dict[str, object]:
        return self._execute(
            HelperRequest(capability=HostCapability.HOST_HEALTH, target=None, params={})
        )

    def service_status(self, target: OperationalTarget) -> dict[str, object]:
        helper_target = target.host_helper_service_target or target.key
        return self._execute(
            HelperRequest(
                capability=HostCapability.SERVICE_STATUS,
                target=helper_target,
                params={},
            )
        )

    def service_logs(self, target: OperationalTarget, *, lines: int) -> dict[str, object]:
        if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1 or lines > HOST_HELPER_MAX_LOG_LINES:
            raise ToolAdapterError("invalid_log_line_count")
        helper_target = target.host_helper_log_target or target.key
        return self._execute(
            HelperRequest(
                capability=HostCapability.LOGS_RECENT,
                target=helper_target,
                params={"lines": lines},
            )
        )

    def service_restart(self, target: OperationalTarget) -> dict[str, object]:
        return self._execute(
            HelperRequest(
                capability=HostCapability.SERVICE_RESTART,
                target=target.key,
                params={},
            )
        )

    def service_recover(self, target: OperationalTarget, *, component: str) -> dict[str, object]:
        return self._execute(
            HelperRequest(
                capability=HostCapability.SERVICE_RECOVER,
                target=target.key,
                params={"component": component},
            )
        )

    def deployment_deploy(self, target: OperationalTarget) -> dict[str, object]:
        return self._execute(
            HelperRequest(
                capability=HostCapability.DEPLOYMENT_DEPLOY,
                target=target.key,
                params={},
            )
        )

    def deployment_rollback(self, target: OperationalTarget, release_id: str) -> dict[str, object]:
        if (
            not isinstance(release_id, str)
            or not release_id
            or len(release_id) > 128
            or not release_id.isascii()
            or any(not (char.isalnum() or char in "._-") for char in release_id)
        ):
            raise ToolAdapterError("invalid_release_id")
        return self._execute(
            HelperRequest(
                capability=HostCapability.DEPLOYMENT_ROLLBACK,
                target=target.key,
                params={"release_id": release_id},
            )
        )


OperationalHostTransport = HostHelperOperationalTransport
