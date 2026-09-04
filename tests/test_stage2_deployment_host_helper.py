import pytest

from ai_hq.host_helper.contracts import (
    HelperRequest,
    HostAllowLists,
    HostCapability,
)
from ai_hq.host_helper.executor import (
    CompletedCommand,
    HostExecutor,
)


def completed(stdout=""):
    return CompletedCommand(
        returncode=0,
        stdout=stdout,
        stderr="",
    )


class RecordingRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        return completed("ok")


def allow_lists():
    return HostAllowLists(
        services=frozenset({"ai-hq"}),
        containers=frozenset(),
        logs=frozenset(),
    )


def test_deploy_uses_only_trusted_server_entrypoint():
    runner = RecordingRunner()
    executor = HostExecutor(
        allow_lists(),
        command_runner=runner,
    )

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.DEPLOYMENT_DEPLOY,
            target="ai-hq",
            params={},
        )
    )

    assert response.ok is True
    assert response.target == "ai-hq"
    assert runner.calls == [
        [
            "/opt/ai-hq/bin/controlled-deploy",
            "ai-hq",
        ]
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"command": "sh"},
        {"executable": "/bin/sh"},
        {"path": "/tmp/evil"},
        {"argv": ["sh", "-c", "id"]},
        {"host": "attacker"},
    ],
)
def test_deploy_rejects_mission_controlled_execution_fields(params):
    runner = RecordingRunner()
    executor = HostExecutor(
        allow_lists(),
        command_runner=runner,
    )

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.DEPLOYMENT_DEPLOY,
            target="ai-hq",
            params=params,
        )
    )

    assert response.ok is False
    assert runner.calls == []


def test_rollback_appends_only_validated_release_id():
    runner = RecordingRunner()
    executor = HostExecutor(
        allow_lists(),
        command_runner=runner,
    )

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.DEPLOYMENT_ROLLBACK,
            target="ai-hq",
            params={"release_id": "release-2.83.0"},
        )
    )

    assert response.ok is True
    assert runner.calls == [
        [
            "/opt/ai-hq/bin/controlled-rollback",
            "ai-hq",
            "release-2.83.0",
        ]
    ]


@pytest.mark.parametrize(
    "release_id",
    [
        "",
        "../previous",
        "/opt/releases/release-1",
        "release 1",
        "release/1",
        "release;id",
        "release$id",
        "é",
        "a" * 129,
    ],
)
def test_rollback_rejects_unsafe_release_id_without_execution(release_id):
    runner = RecordingRunner()
    executor = HostExecutor(
        allow_lists(),
        command_runner=runner,
    )

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.DEPLOYMENT_ROLLBACK,
            target="ai-hq",
            params={"release_id": release_id},
        )
    )

    assert response.ok is False
    assert runner.calls == []


def test_deployment_unknown_target_fails_closed():
    runner = RecordingRunner()
    executor = HostExecutor(
        allow_lists(),
        command_runner=runner,
    )

    response = executor.execute(
        HelperRequest(
            capability=HostCapability.DEPLOYMENT_DEPLOY,
            target="unknown",
            params={},
        )
    )

    assert response.ok is False
    assert runner.calls == []
