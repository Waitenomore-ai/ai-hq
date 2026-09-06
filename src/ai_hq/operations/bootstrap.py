from ai_hq.operations.adapters import (
    DeploymentDeployAdapter,
    DeploymentRollbackAdapter,
    OperationalTransport,
    ServiceLogsAdapter,
    ServiceRecoverAdapter,
    ServiceRestartAdapter,
    ServiceStatusAdapter,
    SystemHealthAdapter,
)
from ai_hq.operations.targets import OperationalTargetRegistry
from ai_hq.tool_gateway.registry import ToolRegistry


def operational_adapters(
    *,
    targets: OperationalTargetRegistry,
    transport: OperationalTransport,
) -> tuple[
    SystemHealthAdapter,
    ServiceStatusAdapter,
    ServiceLogsAdapter,
    ServiceRestartAdapter,
    ServiceRecoverAdapter,
    DeploymentDeployAdapter,
    DeploymentRollbackAdapter,
]:
    return (
        SystemHealthAdapter(targets=targets, transport=transport),
        ServiceStatusAdapter(targets=targets, transport=transport),
        ServiceLogsAdapter(targets=targets, transport=transport),
        ServiceRestartAdapter(targets=targets, transport=transport),
        ServiceRecoverAdapter(targets=targets, transport=transport),
        DeploymentDeployAdapter(targets=targets, transport=transport),
        DeploymentRollbackAdapter(targets=targets, transport=transport),
    )


def build_operational_tool_registry(
    *,
    targets: OperationalTargetRegistry,
    transport: OperationalTransport,
) -> ToolRegistry:
    """Build the immutable operational registry, including bounded recovery."""
    return ToolRegistry(
        operational_adapters(
            targets=targets,
            transport=transport,
        )
    )
