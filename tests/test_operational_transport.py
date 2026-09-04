from dataclasses import dataclass, field

from ai_hq.operations.targets import OperationalTarget
from ai_hq.operations.transport import SubprocessOperationalTransport


@dataclass
class Completed:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class RecordingRunner:
    calls: list[tuple[list[str], dict]] = field(default_factory=list)
    result: Completed = field(default_factory=Completed)

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return self.result


def target():
    return OperationalTarget(
        key="ai-hq",
        service_unit="ai-hq.service",
        log_unit="ai-hq.service",
        allowed_capabilities=frozenset({
            "system.health.read",
            "service.status.read",
            "service.logs.read",
            "service.restart",
        }),
    )


def test_status_uses_fixed_systemctl_argv():
    runner = RecordingRunner(result=Completed(stdout="active\n"))
    transport = SubprocessOperationalTransport(runner=runner)

    result = transport.service_status(target())

    argv, kwargs = runner.calls[0]
    assert argv == ["systemctl", "is-active", "ai-hq.service"]
    assert kwargs.get("shell") is not True
    assert result["active"] is True


def test_logs_use_fixed_journalctl_argv():
    runner = RecordingRunner(result=Completed(stdout="one\ntwo\n"))
    transport = SubprocessOperationalTransport(runner=runner)

    result = transport.service_logs(target(), lines=100)

    argv, kwargs = runner.calls[0]
    assert argv == [
        "journalctl",
        "--unit",
        "ai-hq.service",
        "--lines",
        "100",
        "--no-pager",
    ]
    assert kwargs.get("shell") is not True
    assert result["lines"] == ["one", "two"]


def test_restart_uses_registered_unit_only():
    runner = RecordingRunner()
    transport = SubprocessOperationalTransport(runner=runner)

    result = transport.service_restart(target())

    argv, kwargs = runner.calls[0]
    assert argv == ["systemctl", "restart", "ai-hq.service"]
    assert kwargs.get("shell") is not True
    assert result["restarted"] is True


def test_health_is_bounded_service_observation():
    runner = RecordingRunner(result=Completed(stdout="active\n"))
    transport = SubprocessOperationalTransport(runner=runner)

    result = transport.system_health(target())

    assert result == {
        "target": "ai-hq",
        "service_active": True,
    }
    assert runner.calls[0][0] == [
        "systemctl",
        "is-active",
        "ai-hq.service",
    ]
