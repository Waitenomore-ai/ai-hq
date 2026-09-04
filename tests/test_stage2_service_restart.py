import pytest

from ai_hq.host_helper.contracts import (
    HelperRequest,
    HostAllowLists,
    HostCapability,
    validate_request,
)
from ai_hq.host_helper.executor import CompletedCommand, HostExecutor


ALLOW = HostAllowLists(
    services=frozenset({"ai-hq", "dripvid"}),
    containers=frozenset(),
    logs=frozenset({"ai-hq", "dripvid"}),
)


def test_restart_request_accepts_only_allowlisted_service():
    request = validate_request(
        {
            "capability": "service.restart",
            "target": "dripvid",
            "params": {},
        },
        ALLOW,
    )

    assert request == HelperRequest(
        capability=HostCapability.SERVICE_RESTART,
        target="dripvid",
        params={},
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "capability": "service.restart",
            "target": "ssh",
            "params": {},
        },
        {
            "capability": "service.restart",
            "target": "dripvid.service",
            "params": {},
        },
        {
            "capability": "service.restart",
            "target": "dripvid",
            "params": {"unit": "ssh.service"},
        },
        {
            "capability": "service.restart",
            "target": "dripvid",
            "params": {"command": "whoami"},
        },
    ],
)
def test_restart_request_fails_closed(payload):
    with pytest.raises((TypeError, ValueError)):
        validate_request(payload, ALLOW)


def test_restart_uses_fixed_argv_and_then_reads_status():
    calls = []

    def runner(argv, timeout):
        calls.append((argv, timeout))

        if argv[:2] == ["systemctl", "restart"]:
            return CompletedCommand(0, "", "")

        return CompletedCommand(
            0,
            (
                "ActiveState=active\n"
                "SubState=running\n"
                "LoadState=loaded\n"
                "UnitFileState=enabled\n"
            ),
            "",
        )

    executor = HostExecutor(ALLOW, command_runner=runner)

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.SERVICE_RESTART,
            target="dripvid",
            params={},
        )
    )

    assert response.ok is True
    assert response.data["restarted"] is True
    assert response.data["active_state"] == "active"

    assert calls[0][0] == [
        "systemctl",
        "restart",
        "dripvid.service",
    ]

    assert calls[1][0] == [
        "systemctl",
        "show",
        "dripvid.service",
        "--no-page",
        "--property=ActiveState,SubState,LoadState,UnitFileState",
    ]

    for argv, _timeout in calls:
        assert argv[0] == "systemctl"
        assert "ssh.service" not in argv
        assert "sh" not in argv
        assert "bash" not in argv


def test_unknown_restart_target_never_reaches_command_runner():
    calls = []

    def runner(argv, timeout):
        calls.append((argv, timeout))
        return CompletedCommand(0, "", "")

    executor = HostExecutor(ALLOW, command_runner=runner)

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.SERVICE_RESTART,
            target="ssh",
            params={},
        )
    )

    assert response.ok is False
    assert response.error == "unknown target"
    assert calls == []
