import pytest

from ai_hq.host_helper.contracts import HostAllowLists, HostCapability, validate_request


@pytest.fixture
def allow_lists() -> HostAllowLists:
    return HostAllowLists(
        services=frozenset({"ai-hq", "nginx", "dripvid"}),
        containers=frozenset({"ai-hq-web", "ai-hq-worker"}),
        logs=frozenset({"ai-hq", "nginx", "dripvid"}),
        diagnostic_services=frozenset({"dripvid-mcp", "cloudflared", "postgresql"}),
        diagnostic_logs=frozenset({"dripvid-mcp", "cloudflared", "postgresql"}),
    )


@pytest.mark.parametrize("target", ["dripvid-mcp", "cloudflared", "postgresql"])
def test_diagnostic_services_are_readable(allow_lists, target):
    request = validate_request(
        {"capability": "service.status", "target": target, "params": {}},
        allow_lists,
    )

    assert request.capability is HostCapability.SERVICE_STATUS
    assert request.target == target


@pytest.mark.parametrize("target", ["dripvid-mcp", "cloudflared", "postgresql"])
def test_diagnostic_services_cannot_use_generic_restart(allow_lists, target):
    with pytest.raises(ValueError, match="unknown target"):
        validate_request(
            {"capability": "service.restart", "target": target, "params": {}},
            allow_lists,
        )


@pytest.mark.parametrize("target", ["dripvid-mcp", "cloudflared", "postgresql"])
def test_diagnostic_services_can_read_bounded_logs(allow_lists, target):
    request = validate_request(
        {"capability": "logs.recent", "target": target, "params": {"lines": 100}},
        allow_lists,
    )

    assert request.capability is HostCapability.LOGS_RECENT
    assert request.target == target
    assert request.params == {"lines": 100}


def test_diagnostic_service_sets_do_not_expand_recovery_target():
    allow_lists = HostAllowLists(
        services=frozenset({"dripvid"}),
        containers=frozenset(),
        logs=frozenset({"dripvid"}),
        diagnostic_services=frozenset({"postgresql"}),
        diagnostic_logs=frozenset({"postgresql"}),
    )

    with pytest.raises(ValueError, match="unknown target"):
        validate_request(
            {
                "capability": "service.recover",
                "target": "postgresql",
                "params": {"component": "database"},
            },
            allow_lists,
        )
