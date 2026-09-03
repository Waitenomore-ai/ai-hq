import pytest

from ai_hq.departments.commander import UnsupportedMission, route_sysadmin_mission
from ai_hq.host_helper.contracts import HostCapability
from ai_hq.missions.models import MissionRisk


@pytest.mark.parametrize(
    ("title", "capability", "target", "params"),
    [
        ("Check AI HQ health", HostCapability.HOST_HEALTH, None, {}),
        ("Check disk and memory", HostCapability.HOST_RESOURCES, None, {}),
        ("Is Nginx running?", HostCapability.SERVICE_STATUS, "nginx", {}),
        ("Show recent DripVid logs", HostCapability.LOGS_RECENT, "dripvid", {"lines": 100}),
        (
            "Check AI HQ web container",
            HostCapability.CONTAINER_STATUS,
            "ai-hq-web",
            {},
        ),
    ],
)
def test_routes_supported_sysadmin_missions(title, capability, target, params):
    action = route_sysadmin_mission(title)

    assert action.owner_agent == "sysadmin"
    assert action.capability is capability
    assert action.target == target
    assert action.params == params
    assert action.risk is MissionRisk.GREEN


@pytest.mark.parametrize(
    "title",
    [
        "fix nginx",
        "restart dripvid",
        "run ls",
        "delete logs",
        "Write me a poem",
    ],
)
def test_rejects_unsupported_or_mutating_missions(title):
    with pytest.raises(UnsupportedMission):
        route_sysadmin_mission(title)
