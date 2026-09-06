from typing import Protocol

from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry
from ai_hq.recovery.policy import RECOVERY_COMPONENTS
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest

DEFAULT_LOG_LINES = 100
MAX_LOG_LINES = 500


class OperationalTransport(Protocol):
    def system_health(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]: ...

    def service_status(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]: ...

    def service_logs(
        self,
        target: OperationalTarget,
        *,
        lines: int,
    ) -> dict[str, object]: ...

    def service_restart(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]: ...

    def service_recover(
        self,
        target: OperationalTarget,
        *,
        component: str,
    ) -> dict[str, object]: ...

    def deployment_deploy(
        self,
        target: OperationalTarget,
    ) -> dict[str, object]: ...

    def deployment_rollback(
        self,
        target: OperationalTarget,
        release_id: str,
    ) -> dict[str, object]: ...


class _OperationalAdapter:
    capability: str

    def __init__(
        self,
        *,
        targets: OperationalTargetRegistry,
        transport: OperationalTransport,
    ) -> None:
        self.targets = targets
        self.transport = transport

    def _target(self, request: ToolRequest) -> OperationalTarget:
        if request.capability != self.capability:
            raise ToolAdapterError("capability_mismatch")

        try:
            target = self.targets.require(request.target)
        except ValueError:
            raise ToolAdapterError("unknown_operational_target") from None

        if not target.allows(self.capability):
            raise ToolAdapterError("target_capability_denied")

        return target

    @staticmethod
    def _require_no_params(request: ToolRequest) -> None:
        if request.params:
            raise ToolAdapterError("unexpected_operational_parameters")


class SystemHealthAdapter(_OperationalAdapter):
    capability = "system.health.read"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)
        self._require_no_params(request)
        return self.transport.system_health(target)


class ServiceStatusAdapter(_OperationalAdapter):
    capability = "service.status.read"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)
        self._require_no_params(request)
        return self.transport.service_status(target)


class ServiceLogsAdapter(_OperationalAdapter):
    capability = "service.logs.read"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)

        if set(request.params) - {"lines"}:
            raise ToolAdapterError("unexpected_operational_parameters")

        lines = request.params.get("lines", DEFAULT_LOG_LINES)

        if isinstance(lines, bool) or not isinstance(lines, int):
            raise ToolAdapterError("invalid_log_line_count")

        if lines < 1 or lines > MAX_LOG_LINES:
            raise ToolAdapterError("invalid_log_line_count")

        return self.transport.service_logs(target, lines=lines)


class ServiceRestartAdapter(_OperationalAdapter):
    capability = "service.restart"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)
        self._require_no_params(request)

        if not request.mutates_external_state:
            raise ToolAdapterError("restart_requires_mutation_flag")

        return self.transport.service_restart(target)


class ServiceRecoverAdapter(_OperationalAdapter):
    capability = "service.recover"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)

        if target.key != "dripvid":
            raise ToolAdapterError("recovery_target_denied")

        if set(request.params) != {"component"}:
            raise ToolAdapterError("invalid_recovery_parameters")

        component = request.params.get("component")
        if not isinstance(component, str) or component not in RECOVERY_COMPONENTS:
            raise ToolAdapterError("invalid_recovery_component")

        if not request.mutates_external_state:
            raise ToolAdapterError("recovery_requires_mutation_flag")

        method = getattr(self.transport, "service_recover", None)
        if method is None:
            raise ToolAdapterError("recovery_transport_unavailable")

        return method(target, component=component)


class DeploymentDeployAdapter(_OperationalAdapter):
    capability = "deployment.deploy"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)
        self._require_no_params(request)

        if not request.mutates_external_state:
            raise ToolAdapterError("deployment_requires_mutation_flag")

        method = getattr(self.transport, "deployment_deploy", None)
        if method is None:
            raise ToolAdapterError("deployment_transport_unavailable")

        return method(target)


class DeploymentRollbackAdapter(_OperationalAdapter):
    capability = "deployment.rollback"

    def execute(self, request: ToolRequest) -> dict[str, object]:
        target = self._target(request)

        if set(request.params) != {"release_id"}:
            raise ToolAdapterError("invalid_rollback_parameters")

        release_id = request.params.get("release_id")

        if not isinstance(release_id, str):
            raise ToolAdapterError("invalid_release_id")

        if not release_id or len(release_id) > 128:
            raise ToolAdapterError("invalid_release_id")

        if not release_id.isascii():
            raise ToolAdapterError("invalid_release_id")

        if any(not (char.isalnum() or char in "._-") for char in release_id):
            raise ToolAdapterError("invalid_release_id")

        if not request.mutates_external_state:
            raise ToolAdapterError("rollback_requires_mutation_flag")

        method = getattr(self.transport, "deployment_rollback", None)
        if method is None:
            raise ToolAdapterError("deployment_transport_unavailable")

        return method(target, release_id)
