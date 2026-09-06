import subprocess

import pytest

from ai_hq.host_helper.contracts import HelperRequest, HostAllowLists, HostCapability
from ai_hq.host_helper.executor import MAX_RESPONSE_BYTES, CompletedCommand, HostExecutor


@pytest.fixture
def allow_lists() -> HostAllowLists:
    return HostAllowLists(
        services=frozenset({"ai-hq", "nginx", "dripvid"}),
        containers=frozenset({"ai-hq-web", "ai-hq-worker"}),
        logs=frozenset({"ai-hq", "nginx", "dripvid"}),
    )


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CompletedCommand | Exception]):
        self.responses = responses
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv: list[str], timeout: float) -> CompletedCommand:
        self.calls.append((argv, timeout))
        response = self.responses[tuple(argv)]
        if isinstance(response, Exception):
            raise response
        return response


def test_service_status_uses_fixed_systemd_mapping(allow_lists: HostAllowLists):
    argv = [
        "systemctl",
        "show",
        "nginx.service",
        "--no-page",
        "--property=ActiveState,SubState,LoadState,UnitFileState",
    ]
    runner = FakeRunner({tuple(argv): CompletedCommand(0, "ActiveState=active\nSubState=running\n", "")})
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(HostCapability.SERVICE_STATUS, "nginx", {})
    )

    assert response.ok is True
    assert runner.calls[0][0] == argv
    assert response.data["active_state"] == "active"
    assert response.data["sub_state"] == "running"


def test_container_status_uses_fixed_docker_name(allow_lists: HostAllowLists):
    argv = [
        "docker",
        "inspect",
        "ai-hq-web-1",
        "--format",
        "{{json .State}}",
    ]
    runner = FakeRunner(
        {tuple(argv): CompletedCommand(0, '{"Status":"running","Health":{"Status":"healthy"}}', "")}
    )
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(HostCapability.CONTAINER_STATUS, "ai-hq-web", {})
    )

    assert response.ok is True
    assert runner.calls[0][0] == argv
    assert response.data == {"status": "running", "health": "healthy"}


def test_dripvid_is_not_exposed_as_container_target(allow_lists: HostAllowLists):
    runner = FakeRunner({})
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(HostCapability.CONTAINER_STATUS, "dripvid", {})
    )

    assert response.ok is False
    assert response.error == "unknown target"
    assert runner.calls == []


def test_logs_recent_uses_bounded_fixed_journal_target_and_redacts_secrets(
    allow_lists: HostAllowLists,
):
    argv = [
        "journalctl",
        "-u",
        "dripvid.service",
        "-n",
        "25",
        "--no-pager",
        "-o",
        "short-iso",
    ]
    runner = FakeRunner(
        {tuple(argv): CompletedCommand(0, "started\nAPI_TOKEN=abc123\npassword=hunter2\n", "")}
    )
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(HostCapability.LOGS_RECENT, "dripvid", {"lines": 25})
    )

    assert response.ok is True
    assert runner.calls[0][0] == argv
    text = response.data["text"]
    assert "abc123" not in text
    assert "hunter2" not in text
    assert "[REDACTED]" in text


def test_logs_recent_truncates_to_response_byte_limit(allow_lists: HostAllowLists):
    argv = [
        "journalctl",
        "-u",
        "dripvid.service",
        "-n",
        "200",
        "--no-pager",
        "-o",
        "short-iso",
    ]
    runner = FakeRunner({tuple(argv): CompletedCommand(0, "x" * (MAX_RESPONSE_BYTES + 100), "")})
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(HostCapability.LOGS_RECENT, "dripvid", {"lines": 200})
    )

    assert response.ok is True
    assert response.data["truncated"] is True
    assert len(response.data["text"].encode("utf-8")) <= MAX_RESPONSE_BYTES


def test_command_timeout_returns_bounded_error(allow_lists: HostAllowLists):
    argv = [
        "systemctl",
        "show",
        "nginx.service",
        "--no-page",
        "--property=ActiveState,SubState,LoadState,UnitFileState",
    ]
    runner = FakeRunner({tuple(argv): subprocess.TimeoutExpired(argv, 3)})
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(
        HelperRequest(HostCapability.SERVICE_STATUS, "nginx", {})
    )

    assert response.ok is False
    assert response.error == "timeout"


def test_host_health_uses_only_fixed_commands(allow_lists: HostAllowLists):
    responses = {
        ("uptime", "-p"): CompletedCommand(0, "up 2 days", ""),
        ("cat", "/proc/loadavg"): CompletedCommand(0, "0.10 0.20 0.30 1/100 1\n", ""),
    }
    runner = FakeRunner(responses)
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(HelperRequest(HostCapability.HOST_HEALTH, None, {}))

    assert response.ok is True
    assert [call[0] for call in runner.calls] == [["uptime", "-p"], ["cat", "/proc/loadavg"]]


def test_host_resources_reads_only_fixed_resource_set(allow_lists: HostAllowLists):
    responses = {
        ("cat", "/proc/loadavg"): CompletedCommand(0, "0.10 0.20 0.30 1/100 1\n", ""),
        ("free", "-b"): CompletedCommand(
            0,
            "              total        used        free\nMem:     1000 400 600\nSwap:    0 0 0\n",
            "",
        ),
        ("df", "-B1", "/"): CompletedCommand(
            0,
            "Filesystem 1B-blocks Used Available Use% Mounted on\n/dev/root 10000 2500 7500 25% /\n",
            "",
        ),
    }
    runner = FakeRunner(responses)
    executor = HostExecutor(allow_lists, command_runner=runner)

    response = executor.execute(HelperRequest(HostCapability.HOST_RESOURCES, None, {}))

    assert response.ok is True
    assert [call[0] for call in runner.calls] == [
        ["cat", "/proc/loadavg"],
        ["free", "-b"],
        ["df", "-B1", "/"],
    ]
    assert response.data["memory"]["total_bytes"] == 1000
    assert response.data["filesystem"]["path"] == "/"


def test_dripvid_readiness_uses_only_fixed_host_probe_and_bounds_output(
    allow_lists: HostAllowLists,
):
    calls = []

    def readiness_runner(url, timeout, limit):
        calls.append((url, timeout, limit))
        return {
            "reachable": True,
            "status_code": 200,
            "ok": True,
            "database": True,
            "jellyfin": True,
            "radarr": True,
            "sonarr": True,
            "qbittorrent": True,
            "requestSync": True,
            "storage": {
                "available": True,
                "writable": True,
                "belowReserve": False,
                "freeBytes": 959790956544,
                "reserveBytes": 53687091200,
                "root": "/mnt/TV",
            },
            "apiKey": "secret",
            "root": "/mnt/TV",
            "error": None,
        }

    executor = HostExecutor(allow_lists, readiness_runner=readiness_runner)
    response = executor.execute(
        HelperRequest(HostCapability.DRIPVID_READINESS, None, {})
    )

    assert calls == [("http://127.0.0.1:3000/health/ready", 3.0, 64 * 1024)]
    assert response.ok is True
    assert response.target is None
    assert response.data == {
        "reachable": True,
        "status_code": 200,
        "ok": True,
        "database": True,
        "jellyfin": True,
        "radarr": True,
        "sonarr": True,
        "qbittorrent": True,
        "requestSync": True,
        "storage": {
            "available": True,
            "writable": True,
            "belowReserve": False,
            "freeBytes": 959790956544,
            "reserveBytes": 53687091200,
        },
        "error": None,
    }


def test_dripvid_readiness_timeout_fails_closed(allow_lists: HostAllowLists):
    def readiness_runner(url, timeout, limit):
        raise TimeoutError

    executor = HostExecutor(allow_lists, readiness_runner=readiness_runner)
    response = executor.execute(
        HelperRequest(HostCapability.DRIPVID_READINESS, None, {})
    )

    assert response.ok is True
    assert response.data == {
        "reachable": False,
        "status_code": None,
        "ok": False,
        "error": "timeout",
    }


def test_dripvid_readiness_preserves_only_bounded_parse_error(
    allow_lists: HostAllowLists,
):
    def readiness_runner(url, timeout, limit):
        return {
            "reachable": True,
            "status_code": 200,
            "ok": False,
            "error": "invalid_json",
            "body": "secret raw response",
        }

    executor = HostExecutor(allow_lists, readiness_runner=readiness_runner)
    response = executor.execute(
        HelperRequest(HostCapability.DRIPVID_READINESS, None, {})
    )

    assert response.ok is True
    assert response.data == {
        "reachable": True,
        "status_code": 200,
        "ok": False,
        "error": "invalid_json",
    }


def test_logs_recent_survives_journalctl_slower_than_three_seconds():
    """journalctl on a busy/self-referential unit can legitimately take
    slightly longer than 3s; the executor's command timeout must not be
    so tight that normal production latency is treated as a failure."""
    import subprocess
    from ai_hq.host_helper.contracts import HelperRequest, HostAllowLists, HostCapability
    from ai_hq.host_helper.executor import HostExecutor, CompletedCommand

    def slow_runner(argv, timeout):
        if timeout < 3.2:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)
        return CompletedCommand(0, "2026-09-05 log line\n", "")

    allow_lists = HostAllowLists(
        services=frozenset({"ai-hq"}),
        containers=frozenset(),
        logs=frozenset({"ai-hq"}),
    )
    executor = HostExecutor(allow_lists, command_runner=slow_runner)
    request = HelperRequest(
        capability=HostCapability.LOGS_RECENT,
        target="ai-hq",
        params={"lines": 100},
    )

    response = executor.execute(request)

    assert response.ok is True
    assert response.error is None
