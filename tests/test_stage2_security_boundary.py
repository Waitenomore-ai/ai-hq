import pytest

from ai_hq.host_helper.contracts import (
    HostAllowLists,
    HostCapability,
    validate_request,
)
from ai_hq.tool_gateway.contracts import ToolRequest


def _request(capability, target, params=None):
    return {
        "capability": capability.value,
        "target": target,
        "params": params or {},
    }


def test_restart_rejects_unregistered_service():
    allow = HostAllowLists(
        services=frozenset({"ai-hq", "dripvid"}),
        containers=frozenset(),
        logs=frozenset(),
    )

    with pytest.raises(ValueError):
        validate_request(
            _request(
                HostCapability.SERVICE_RESTART,
                "postgresql",
            ),
            allow,
        )


def test_restart_rejects_raw_systemd_unit():
    allow = HostAllowLists(
        services=frozenset({"ai-hq", "dripvid"}),
        containers=frozenset(),
        logs=frozenset(),
    )

    with pytest.raises(ValueError):
        validate_request(
            _request(
                HostCapability.SERVICE_RESTART,
                "dripvid.service",
            ),
            allow,
        )


def test_restart_rejects_command_injection_parameters():
    allow = HostAllowLists(
        services=frozenset({"dripvid"}),
        containers=frozenset(),
        logs=frozenset(),
    )

    for params in (
        {"command": "rm -rf /"},
        {"unit": "ssh.service"},
        {"argv": ["sh", "-c", "id"]},
        {"shell": True},
        {"path": "/etc/passwd"},
    ):
        with pytest.raises(ValueError):
            validate_request(
                _request(
                    HostCapability.SERVICE_RESTART,
                    "dripvid",
                    params,
                ),
                allow,
            )


def test_no_arbitrary_shell_capability_exists():
    values = {capability.value for capability in HostCapability}

    assert "shell.execute" not in values
    assert "command.execute" not in values
    assert "subprocess.execute" not in values
    assert "filesystem.write" not in values


def test_tool_request_has_no_command_or_executable_field():
    fields = set(ToolRequest.__dataclass_fields__)

    assert "command" not in fields
    assert "executable" not in fields
    assert "argv" not in fields
    assert "shell" not in fields


def test_host_helper_restart_is_logical_target_only():
    allow = HostAllowLists(
        services=frozenset({"ai-hq", "dripvid"}),
        containers=frozenset(),
        logs=frozenset(),
    )

    validated = validate_request(
        _request(
            HostCapability.SERVICE_RESTART,
            "dripvid",
        ),
        allow,
    )

    assert validated.target == "dripvid"
    assert validated.params == {}


def test_unknown_host_helper_target_fails_closed():
    allow = HostAllowLists(
        services=frozenset({"ai-hq"}),
        containers=frozenset(),
        logs=frozenset(),
    )

    with pytest.raises(ValueError):
        validate_request(
            _request(
                HostCapability.SERVICE_RESTART,
                "unknown-target",
            ),
            allow,
        )
