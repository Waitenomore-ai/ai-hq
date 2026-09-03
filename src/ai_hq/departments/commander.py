import re
from dataclasses import dataclass

from ai_hq.host_helper.contracts import HostCapability
from ai_hq.missions.models import MissionRisk


@dataclass(frozen=True, slots=True)
class RoutedAction:
    owner_agent: str
    capability: HostCapability
    target: str | None
    params: dict[str, object]
    risk: MissionRisk


class UnsupportedMission(ValueError):
    """Raised when Commander cannot map a mission to a safe read-only action."""


_MUTATION_PATTERN = re.compile(
    r"\b(fix|restart|stop|start|delete|remove|write|edit|update|deploy|install|uninstall|run|execute|kill)\b"
)

_ROUTES: dict[str, tuple[HostCapability, str | None, dict[str, object]]] = {
    "check ai hq health": (HostCapability.HOST_HEALTH, None, {}),
    "check disk and memory": (HostCapability.HOST_RESOURCES, None, {}),
    "is nginx running?": (HostCapability.SERVICE_STATUS, "nginx", {}),
    "show recent dripvid logs": (HostCapability.LOGS_RECENT, "dripvid", {"lines": 100}),
    "check ai hq web container": (HostCapability.CONTAINER_STATUS, "ai-hq-web", {}),
}


def _normalize_title(title: str) -> str:
    if not isinstance(title, str):
        raise UnsupportedMission("unsupported mission")
    return " ".join(title.casefold().split())


def route_sysadmin_mission(title: str) -> RoutedAction:
    normalized = _normalize_title(title)
    if _MUTATION_PATTERN.search(normalized):
        raise UnsupportedMission("unsupported mission")

    route = _ROUTES.get(normalized)
    if route is None:
        raise UnsupportedMission("unsupported mission")

    capability, target, params = route
    return RoutedAction(
        owner_agent="sysadmin",
        capability=capability,
        target=target,
        params=dict(params),
        risk=MissionRisk.GREEN,
    )
