import pytest

from ai_hq.host_helper.contracts import HostAllowLists, HostCapability, validate_request


@pytest.fixture
def allow_lists() -> HostAllowLists:
    return HostAllowLists(
        services=frozenset({"ai-hq", "nginx", "dripvid"}),
        containers=frozenset({"ai-hq-web", "ai-hq-worker", "dripvid"}),
        logs=frozenset({"ai-hq", "nginx", "dripvid"}),
    )


def test_host_capabilities_are_exactly_the_controlled_set():
    assert {capability.value for capability in HostCapability} == {
        "host.health",
        "host.resources",
        "service.status",
        "service.restart",
        "deployment.deploy",
        "deployment.rollback",
        "container.status",
        "logs.recent",
    }


def test_unknown_capability_is_rejected(allow_lists: HostAllowLists):
    with pytest.raises(ValueError, match="unknown capability"):
        validate_request({"capability": "shell.exec", "params": {}}, allow_lists)


@pytest.mark.parametrize(
    ("capability", "target"),
    [
        ("service.status", "ssh"),
        ("container.status", "postgres"),
        ("logs.recent", "auth"),
    ],
)
def test_targeted_capabilities_reject_unknown_targets(
    allow_lists: HostAllowLists,
    capability: str,
    target: str,
):
    with pytest.raises(ValueError, match="unknown target"):
        validate_request(
            {"capability": capability, "target": target, "params": {}},
            allow_lists,
        )


@pytest.mark.parametrize("capability", ["host.health", "host.resources"])
def test_host_capabilities_reject_caller_controlled_fields(
    allow_lists: HostAllowLists,
    capability: str,
):
    for payload in (
        {"capability": capability, "target": "nginx", "params": {}},
        {"capability": capability, "params": {"path": "/etc/passwd"}},
        {"capability": capability, "params": {"command": "id"}},
    ):
        with pytest.raises(ValueError):
            validate_request(payload, allow_lists)


def test_logs_recent_accepts_only_bounded_line_count(allow_lists: HostAllowLists):
    request = validate_request(
        {"capability": "logs.recent", "target": "dripvid", "params": {"lines": 100}},
        allow_lists,
    )
    assert request.capability is HostCapability.LOGS_RECENT
    assert request.target == "dripvid"
    assert request.params == {"lines": 100}

    upper_bound = validate_request(
        {"capability": "logs.recent", "target": "dripvid", "params": {"lines": 500}},
        allow_lists,
    )
    assert upper_bound.params == {"lines": 500}

    for lines in (0, 501, -1, "100", 1.5):
        with pytest.raises(ValueError, match="lines"):
            validate_request(
                {"capability": "logs.recent", "target": "dripvid", "params": {"lines": lines}},
                allow_lists,
            )


def test_unknown_parameter_keys_are_rejected(allow_lists: HostAllowLists):
    with pytest.raises(ValueError, match="unknown parameter"):
        validate_request(
            {
                "capability": "service.status",
                "target": "nginx",
                "params": {"extra": "--all"},
            },
            allow_lists,
        )
