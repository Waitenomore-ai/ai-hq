from ai_hq.operations.adapters import (
    OperationalTransport,
    ServiceLogsAdapter,
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
]:
    return (
        SystemHealthAdapter(targets=targets, transport=transport),
        ServiceStatusAdapter(targets=targets, transport=transport),
        ServiceLogsAdapter(targets=targets, transport=transport),
        ServiceRestartAdapter(targets=targets, transport=transport),
    )


def build_operational_tool_registry(
    *,
    targets: OperationalTargetRegistry,
    transport: OperationalTransport,
) -> ToolRegistry:
    """
    Build a ToolRegistry using its existing immutable-after-construction
    contract. Stage 2 does not add a mutable registry back door.
    """
    return ToolRegistry(
        operational_adapters(
            targets=targets,
            transport=transport,
        )
    )
