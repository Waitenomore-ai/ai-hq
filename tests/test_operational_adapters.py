from dataclasses import dataclass, field

import pytest

from ai_hq.missions.models import MissionRisk
from ai_hq.operations.adapters import (
    MAX_LOG_LINES,
    ServiceLogsAdapter,
    ServiceRestartAdapter,
    ServiceStatusAdapter,
    SystemHealthAdapter,
)
from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest


@dataclass
class RecordingTransport:
    calls: list[tuple] = field(default_factory=list)

    def system_health(self, target):
        self.calls.append(("health", target.key))
        return {"target": target.key, "healthy": True}

    def service_status(self, target):
        self.calls.append(("status", target.key, target.service_unit))
        return {"target": target.key, "active": True}

    def service_logs(self, target, *, lines):
        self.calls.append(("logs", target.key, target.log_unit, lines))
        return {"target": target.key, "lines": ["hello"]}

    def service_restart(self, target):
        self.calls.append(("restart", target.key, target.service_unit))
        return {"target": target.key, "restarted": True}


def registry():
    return OperationalTargetRegistry([
        OperationalTarget(
            key="ai-hq",
            service_unit="ai-hq.service",
            log_unit="ai-hq.service",
            allowed_capabilities=frozenset({
                "system.health.read",
                "service.status.read",
                "service.logs.read",
                "service.restart",
            }),
        ),
        OperationalTarget(
            key="dripvid",
            service_unit="dripvid.service",
            allowed_capabilities=frozenset({"service.status.read"}),
        ),
    ])


def request(capability, *, target="ai-hq", params=None, mutates=False):
    return ToolRequest(
        mission_id="mission-1",
        agent_key="operator",
        capability=capability,
        target=target,
        risk=MissionRisk.GREEN,
        params=params or {},
        conditions={},
        mutates_external_state=mutates,
    )


def test_health_uses_registered_target():
    transport = RecordingTransport()
    adapter = SystemHealthAdapter(targets=registry(), transport=transport)

    result = adapter.execute(request("system.health.read"))

    assert result["healthy"] is True
    assert transport.calls == [("health", "ai-hq")]


def test_status_rejects_unknown_target():
    transport = RecordingTransport()
    adapter = ServiceStatusAdapter(targets=registry(), transport=transport)

    with pytest.raises(ToolAdapterError):
        adapter.execute(request("service.status.read", target="unknown"))

    assert transport.calls == []


def test_target_without_capability_is_rejected():
    transport = RecordingTransport()
    adapter = ServiceRestartAdapter(targets=registry(), transport=transport)

    with pytest.raises(ToolAdapterError):
        adapter.execute(
            request("service.restart", target="dripvid", mutates=True)
        )

    assert transport.calls == []


@pytest.mark.parametrize("params", [
    {"unit": "evil.service"},
    {"command": "whoami"},
    {"hostname": "other-host"},
    {"path": "/tmp/x"},
])
def test_restart_rejects_mission_controlled_infrastructure(params):
    transport = RecordingTransport()
    adapter = ServiceRestartAdapter(targets=registry(), transport=transport)

    with pytest.raises(ToolAdapterError):
        adapter.execute(
            request("service.restart", params=params, mutates=True)
        )

    assert transport.calls == []


def test_restart_uses_registered_service_unit():
    transport = RecordingTransport()
    adapter = ServiceRestartAdapter(targets=registry(), transport=transport)

    adapter.execute(request("service.restart", mutates=True))

    assert transport.calls == [
        ("restart", "ai-hq", "ai-hq.service")
    ]


def test_logs_default_to_100_lines():
    transport = RecordingTransport()
    adapter = ServiceLogsAdapter(targets=registry(), transport=transport)

    adapter.execute(request("service.logs.read"))

    assert transport.calls == [
        ("logs", "ai-hq", "ai-hq.service", 100)
    ]


@pytest.mark.parametrize("value", [
    0,
    -1,
    MAX_LOG_LINES + 1,
    True,
    "100",
    10.5,
])
def test_logs_reject_invalid_line_count(value):
    transport = RecordingTransport()
    adapter = ServiceLogsAdapter(targets=registry(), transport=transport)

    with pytest.raises(ToolAdapterError):
        adapter.execute(
            request("service.logs.read", params={"lines": value})
        )

    assert transport.calls == []


def test_logs_reject_unknown_parameters():
    transport = RecordingTransport()
    adapter = ServiceLogsAdapter(targets=registry(), transport=transport)

    with pytest.raises(ToolAdapterError):
        adapter.execute(
            request(
                "service.logs.read",
                params={"lines": 10, "unit": "other.service"},
            )
        )

    assert transport.calls == []
