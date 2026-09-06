from dataclasses import dataclass, field
from enum import StrEnum


class HostCapability(StrEnum):
    HOST_HEALTH = "host.health"
    HOST_RESOURCES = "host.resources"
    DRIPVID_READINESS = "dripvid.readiness"
    SERVICE_STATUS = "service.status"
    SERVICE_RESTART = "service.restart"
    SERVICE_RECOVER = "service.recover"
    DEPLOYMENT_DEPLOY = "deployment.deploy"
    DEPLOYMENT_ROLLBACK = "deployment.rollback"
    CONTAINER_STATUS = "container.status"
    LOGS_RECENT = "logs.recent"


RECOVERY_COMPONENT_KEYS = frozenset({"app", "mcp", "proxy", "tunnel", "database"})


@dataclass(frozen=True, slots=True)
class HostAllowLists:
    services: frozenset[str]
    containers: frozenset[str]
    logs: frozenset[str]
    diagnostic_services: frozenset[str] = field(default_factory=frozenset)
    diagnostic_logs: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class HelperRequest:
    capability: HostCapability
    target: str | None
    params: dict[str, object]


@dataclass(frozen=True, slots=True)
class HelperResponse:
    ok: bool
    capability: HostCapability
    target: str | None
    data: dict[str, object]
    error: str | None = None


def _validate_target(capability: HostCapability, target: object, allow_lists: HostAllowLists) -> str:
    if not isinstance(target, str) or not target:
        raise ValueError("unknown target")

    if capability is HostCapability.SERVICE_RECOVER:
        if target != "dripvid" or target not in allow_lists.services:
            raise ValueError("unknown target")
        return target

    if capability is HostCapability.SERVICE_STATUS:
        allowed = allow_lists.services | allow_lists.diagnostic_services
    elif capability in {
        HostCapability.SERVICE_RESTART,
        HostCapability.DEPLOYMENT_DEPLOY,
        HostCapability.DEPLOYMENT_ROLLBACK,
    }:
        allowed = allow_lists.services
    elif capability is HostCapability.CONTAINER_STATUS:
        allowed = allow_lists.containers
    else:
        allowed = allow_lists.logs | allow_lists.diagnostic_logs

    if target not in allowed:
        raise ValueError("unknown target")
    return target


def validate_request(payload: dict, allow_lists: HostAllowLists) -> HelperRequest:
    if not isinstance(payload, dict):
        raise TypeError("invalid request")

    try:
        capability = HostCapability(payload.get("capability"))
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown capability") from exc

    unknown_top_level = set(payload) - {"capability", "target", "params"}
    if unknown_top_level:
        raise ValueError("unknown request field")

    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise TypeError("invalid parameters")

    target = payload.get("target")
    if capability in {
        HostCapability.HOST_HEALTH,
        HostCapability.HOST_RESOURCES,
        HostCapability.DRIPVID_READINESS,
    }:
        if target is not None:
            raise ValueError("target not allowed")
        if params:
            raise ValueError("unknown parameter")
        return HelperRequest(capability=capability, target=None, params={})

    validated_target = _validate_target(capability, target, allow_lists)

    if capability is HostCapability.SERVICE_RECOVER:
        if set(params) != {"component"}:
            raise ValueError("invalid recovery parameters")
        component = params.get("component")
        if not isinstance(component, str) or component not in RECOVERY_COMPONENT_KEYS:
            raise ValueError("invalid recovery component")
        return HelperRequest(
            capability=capability,
            target=validated_target,
            params={"component": component},
        )

    if capability in {
        HostCapability.SERVICE_STATUS,
        HostCapability.SERVICE_RESTART,
        HostCapability.DEPLOYMENT_DEPLOY,
        HostCapability.DEPLOYMENT_ROLLBACK,
        HostCapability.CONTAINER_STATUS,
    }:
        if params:
            raise ValueError("unknown parameter")
        return HelperRequest(capability=capability, target=validated_target, params={})

    unknown_params = set(params) - {"lines"}
    if unknown_params:
        raise ValueError("unknown parameter")

    lines = params.get("lines", 100)
    if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= 500:
        raise ValueError("lines must be an integer between 1 and 500")

    return HelperRequest(
        capability=capability,
        target=validated_target,
        params={"lines": lines},
    )
