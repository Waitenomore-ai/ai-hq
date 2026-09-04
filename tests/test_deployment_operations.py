import pytest

from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry

from ai_hq.operations.adapters import (
    DeploymentDeployAdapter,
    DeploymentRollbackAdapter,
)
from ai_hq.tool_gateway.contracts import ToolAdapterError, ToolRequest
from ai_hq.missions.models import MissionRisk


class FakeTransport:
    def __init__(self):
        self.deploy_calls = []
        self.rollback_calls = []

    def deployment_deploy(self, target):
        self.deploy_calls.append(target.key)
        return {"deployed": target.key}

    def deployment_rollback(self, target, release_id):
        self.rollback_calls.append((target.key, release_id))
        return {
            "rolled_back": target.key,
            "release_id": release_id,
        }


def build_targets():
    target = OperationalTarget(
        key="ai-hq",
        service_unit="ai-hq.service",
        allowed_capabilities=frozenset({
            "deployment.deploy",
            "deployment.rollback",
        }),
        deploy_entrypoint=("trusted-deploy",),
        rollback_entrypoint=("trusted-rollback",),
    )
    return OperationalTargetRegistry([target])


def request(capability, params=None):
    return ToolRequest(
        mission_id="mission-1",
        agent_key="sysadmin",
        capability=capability,
        target="ai-hq",
        risk=MissionRisk.GREEN,
        params=params or {},
        mutates_external_state=True,
    )


def test_deploy_uses_only_logical_target():
    transport = FakeTransport()
    adapter = DeploymentDeployAdapter(
        targets=build_targets(),
        transport=transport,
    )

    result = adapter.execute(request("deployment.deploy"))

    assert result == {"deployed": "ai-hq"}
    assert transport.deploy_calls == ["ai-hq"]


@pytest.mark.parametrize(
    "params",
    [
        {"command": "deploy --force"},
        {"executable": "/bin/sh"},
        {"path": "/opt/releases"},
        {"argv": ["sh", "-c", "id"]},
        {"host": "example.com"},
    ],
)
def test_deploy_rejects_mission_controlled_execution_fields(params):
    adapter = DeploymentDeployAdapter(
        targets=build_targets(),
        transport=FakeTransport(),
    )

    with pytest.raises(ToolAdapterError):
        adapter.execute(request("deployment.deploy", params))


@pytest.mark.parametrize(
    "release_id",
    [
        "release-2.83.0",
        "v2_83_1",
        "2026.09.04",
        "abcXYZ-_.0123456789",
    ],
)
def test_rollback_accepts_safe_release_identifiers(release_id):
    transport = FakeTransport()
    adapter = DeploymentRollbackAdapter(
        targets=build_targets(),
        transport=transport,
    )

    result = adapter.execute(
        request(
            "deployment.rollback",
            {"release_id": release_id},
        )
    )

    assert result["release_id"] == release_id
    assert transport.rollback_calls == [("ai-hq", release_id)]


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
def test_rollback_rejects_unsafe_release_identifiers(release_id):
    adapter = DeploymentRollbackAdapter(
        targets=build_targets(),
        transport=FakeTransport(),
    )

    with pytest.raises(ToolAdapterError):
        adapter.execute(
            request(
                "deployment.rollback",
                {"release_id": release_id},
            )
        )


def test_rollback_rejects_extra_mission_controlled_fields():
    adapter = DeploymentRollbackAdapter(
        targets=build_targets(),
        transport=FakeTransport(),
    )

    with pytest.raises(ToolAdapterError):
        adapter.execute(
            request(
                "deployment.rollback",
                {
                    "release_id": "release-1",
                    "path": "/tmp/evil",
                },
            )
        )
