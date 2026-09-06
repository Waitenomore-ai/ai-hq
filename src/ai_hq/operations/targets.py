from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationalTarget:
    key: str
    service_unit: str
    allowed_capabilities: frozenset[str]
    health_url: str | None = None
    log_unit: str | None = None
    deploy_entrypoint: tuple[str, ...] | None = None
    rollback_entrypoint: tuple[str, ...] | None = None
    host_helper_service_target: str | None = None
    host_helper_log_target: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("operational target key is required")
        if not self.service_unit or not self.service_unit.strip():
            raise ValueError("service unit is required")
        if not self.allowed_capabilities:
            raise ValueError("operational target requires capabilities")

        for capability in self.allowed_capabilities:
            if not capability or not capability.strip() or "*" in capability:
                raise ValueError("invalid operational capability")

        if self.log_unit is not None and not self.log_unit.strip():
            raise ValueError("log unit cannot be empty")
        if self.host_helper_service_target is not None and not self.host_helper_service_target.strip():
            raise ValueError("host helper service target cannot be empty")
        if self.host_helper_log_target is not None and not self.host_helper_log_target.strip():
            raise ValueError("host helper log target cannot be empty")

        for entrypoint in (self.deploy_entrypoint, self.rollback_entrypoint):
            if entrypoint is not None and (not entrypoint or any(not part for part in entrypoint)):
                raise ValueError("invalid operational entrypoint")

    def allows(self, capability: str) -> bool:
        return capability in self.allowed_capabilities


class OperationalTargetRegistry:
    def __init__(self, targets: list[OperationalTarget] | tuple[OperationalTarget, ...]):
        self._targets: dict[str, OperationalTarget] = {}
        for target in targets:
            if target.key in self._targets:
                raise ValueError(f"duplicate operational target: {target.key}")
            self._targets[target.key] = target

    def resolve(self, key: str) -> OperationalTarget | None:
        return self._targets.get(key)

    def require(self, key: str) -> OperationalTarget:
        target = self.resolve(key)
        if target is None:
            raise ValueError(f"unknown operational target: {key}")
        return target
