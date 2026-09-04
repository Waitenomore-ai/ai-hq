from dataclasses import dataclass
from enum import StrEnum


class HostCapability(StrEnum):
    HOST_HEALTH = "host.health"
    HOST_RESOURCES = "host.resources"
    SERVICE_STATUS = "service.status"
    SERVICE_RESTART = "service.restart"
    DEPLOYMENT_DEPLOY = "deployment.deploy"
    DEPLOYMENT_ROLLBACK = "deployment.rollback"
    CONTAINER_STATUS = "container.status"
    LOGS_RECENT = "logs.recent"


@dataclass(frozen=True, slots=True)
class HostAllowLists:
    services: frozenset[str]
    containers: frozenset[str]
    logs: frozenset[str]


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

    if capability in {
        HostCapability.SERVICE_STATUS,
        HostCapability.SERVICE_RESTART,
            HostCapability.DEPLOYMENT_DEPLOY,
            HostCapability.DEPLOYMENT_ROLLBACK,
    }:
        allowed = allow_lists.services
    elif capability is HostCapability.CONTAINER_STATUS:
        allowed = allow_lists.containers
    else:
        allowed = allow_lists.logs

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

    if capability in {HostCapability.HOST_HEALTH, HostCapability.HOST_RESOURCES}:
        if target is not None:
            raise ValueError("target not allowed")
        if params:
            raise ValueError("unknown parameter")
        return HelperRequest(capability=capability, target=None, params={})

    validated_target = _validate_target(capability, target, allow_lists)

    if capability in {
        HostCapability.SERVICE_STATUS,
        HostCapability.SERVICE_RESTART,
            HostCapability.DEPLOYMENT_DEPLOY,
            HostCapability.DEPLOYMENT_ROLLBACK,
        HostCapability.CONTAINER_STATUS,
    }:
        if params:
            raise ValueError("unknown parameter")
        return HelperRequest(
            capability=capability,
            target=validated_target,
            params={},
        )

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
