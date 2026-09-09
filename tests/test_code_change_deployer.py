import pytest

from ai_hq.code_changes.deployer import (
    DeployedRelease,
    OperationalCandidateDeployer,
)
from ai_hq.code_changes.publisher import PublishedCandidate
from ai_hq.operations.targets import (
    OperationalTarget,
    OperationalTargetRegistry,
)

CHANGE_REF = "sha256:" + "a" * 64
COMMIT = "b" * 40
TREE = "c" * 40
BASE = "d" * 40
RELEASE_ID = "dripvid-2026-09-09.rc1"
PRIOR_RELEASE_ID = "dripvid-2026-09-08.prod"


def published_candidate(repository="dripvid"):
    return PublishedCandidate(
        repository=repository,
        change_ref=CHANGE_REF,
        branch_name="ai-hq/candidate/111111111111-aaaaaaaaaaaa",
        commit_sha=COMMIT,
        tree_sha=TREE,
        base_commit=BASE,
    )


class Transport:
    def __init__(self, result=None):
        self.result = result if result is not None else {}
        self.calls = []
        self.key = None

    def deployment_deploy(self, target):
        self.calls.append(target.key)
        return self.result


def targets_for(key, *capabilities):
    return OperationalTargetRegistry(
        [
            OperationalTarget(
                key=key,
                service_unit=f"{key}.service",
                log_unit=f"{key}.service",
                allowed_capabilities=frozenset(capabilities),
            )
        ]
    )


def build_deployer(
    *,
    repository="dripvid",
    result=None,
    target_capabilities=("deployment.deploy",),
):
    transport = Transport(result)
    target = OperationalCandidateDeployer(
        targets=targets_for(repository, *target_capabilities),
        transport=transport,
        repository=repository,
    )
    return target, transport


def test_deployed_release_validates_identity():
    release = DeployedRelease(
        repository="dripvid",
        change_ref=CHANGE_REF,
        release_id=RELEASE_ID,
        prior_release_id=PRIOR_RELEASE_ID,
    )
    assert release.release_id == RELEASE_ID
    assert release.prior_release_id == PRIOR_RELEASE_ID


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository": "other"},
        {"change_ref": "not-a-digest"},
        {"release_id": "bad release"},
        {"release_id": "a" * 129},
        {"release_id": "release-\u00e9"},
        {"prior_release_id": "bad prior"},
    ],
)
def test_deployed_release_fails_closed_on_unsafe_identity(kwargs):
    values = {
        "repository": "dripvid",
        "change_ref": CHANGE_REF,
        "release_id": RELEASE_ID,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        DeployedRelease(**values)


def test_operational_deployer_reports_trusted_release_identity():
    deployer, transport = build_deployer(
        result={
            "deployed": True,
            "release_id": RELEASE_ID,
            "prior_release_id": PRIOR_RELEASE_ID,
        }
    )

    release = deployer.deploy(published_candidate())

    assert transport.calls == ["dripvid"]
    assert release.repository == "dripvid"
    assert release.change_ref == CHANGE_REF
    assert release.release_id == RELEASE_ID
    assert release.prior_release_id == PRIOR_RELEASE_ID


def test_operational_deployer_allows_missing_prior_release():
    deployer, transport = build_deployer(
        result={"deployed": True, "release_id": RELEASE_ID}
    )

    release = deployer.deploy(published_candidate())

    assert release.release_id == RELEASE_ID
    assert release.prior_release_id is None


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"deployed": False},
        {"deployed": True},
        {"deployed": True, "release_id": "bad release"},
        {"deployed": True, "release_id": RELEASE_ID, "prior_release_id": "a" * 129},
    ],
)
def test_operational_deployer_fails_closed_without_trusted_identity(result):
    deployer, transport = build_deployer(result=result)

    with pytest.raises(RuntimeError, match="release|deploy"):
        deployer.deploy(published_candidate())


def test_operational_deployer_denies_ungranted_capability():
    with pytest.raises(ValueError, match="deployment.deploy"):
        build_deployer(target_capabilities=("service.status.read",))


def test_operational_deployer_rejects_unknown_repository():
    transport = Transport()
    with pytest.raises(ValueError, match="deploy target|unknown"):
        OperationalCandidateDeployer(
            targets=targets_for("dripvid", "deployment.deploy"),
            transport=transport,
            repository="other",
        )


def test_operational_deployer_rejects_mismatched_candidate():
    deployer, transport = build_deployer(
        result={"deployed": True, "release_id": RELEASE_ID}
    )

    with pytest.raises(ValueError, match="repository"):
        deployer.deploy(published_candidate(repository="ai-hq"))