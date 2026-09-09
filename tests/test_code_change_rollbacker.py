import pytest

from ai_hq.code_changes.rollbacker import (
    OperationalCandidateRollbacker,
    RolledBackRelease,
    RollbackTarget,
)
from ai_hq.operations.targets import (
    OperationalTarget,
    OperationalTargetRegistry,
)

CHANGE_REF = "sha256:" + "a" * 64
RELEASE_ID = "dripvid-2026-09-08.prod"


class Transport:
    def __init__(self, result=None):
        self.result = result if result is not None else {}
        self.calls = []
        self.key = None

    def deployment_rollback(self, target, release_id):
        self.calls.append((target.key, release_id))
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


def build_rollbacker(
    *,
    repository="dripvid",
    result=None,
    target_capabilities=("deployment.rollback",),
):
    transport = Transport(result)
    rollbacker = OperationalCandidateRollbacker(
        targets=targets_for(repository, *target_capabilities),
        transport=transport,
        repository=repository,
    )
    return rollbacker, transport


def rollback_target(repository="dripvid"):
    return RollbackTarget(repository=repository, change_ref=CHANGE_REF)


def test_rolled_back_release_validates_identity():
    release = RolledBackRelease(
        repository="dripvid",
        change_ref=CHANGE_REF,
        release_id=RELEASE_ID,
    )
    assert release.change_ref == CHANGE_REF
    assert release.release_id == RELEASE_ID


def test_rollback_target_validates_identity():
    target = rollback_target()
    assert target.repository == "dripvid"
    assert target.change_ref == CHANGE_REF


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository": "other"},
        {"change_ref": "not-a-digest"},
        {"release_id": "bad release"},
        {"release_id": "a" * 129},
        {"release_id": "release-\u00e9"},
    ],
)
def test_rolled_back_release_fails_closed_on_unsafe_identity(kwargs):
    values = {
        "repository": "dripvid",
        "change_ref": CHANGE_REF,
        "release_id": RELEASE_ID,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        RolledBackRelease(**values)


def test_operational_rollbacker_confirms_exact_trusted_release():
    rollbacker, transport = build_rollbacker(
        result={"rolled_back": True, "release_id": RELEASE_ID}
    )

    release = rollbacker.rollback(rollback_target(), release_id=RELEASE_ID)

    assert transport.calls == [("dripvid", RELEASE_ID)]
    assert release.repository == "dripvid"
    assert release.change_ref == CHANGE_REF
    assert release.release_id == RELEASE_ID


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"rolled_back": False},
        {"rolled_back": True},
        {"rolled_back": True, "release_id": "bad release"},
        {
            "rolled_back": True,
            "release_id": "dripvid-2026-09-01.other",
        },
    ],
)
def test_operational_rollbacker_fails_closed_without_trusted_identity(result):
    rollbacker, transport = build_rollbacker(result=result)

    with pytest.raises(RuntimeError, match="release|rollback"):
        rollbacker.rollback(rollback_target(), release_id=RELEASE_ID)


def test_operational_rollbacker_rejects_unsafe_requested_release():
    rollbacker, transport = build_rollbacker(
        result={"rolled_back": True, "release_id": RELEASE_ID}
    )

    with pytest.raises(ValueError, match="release"):
        rollbacker.rollback(rollback_target(), release_id="bad release")


def test_operational_rollbacker_denies_ungranted_capability():
    with pytest.raises(ValueError, match="deployment.rollback"):
        build_rollbacker(target_capabilities=("service.status.read",))


def test_operational_rollbacker_rejects_unknown_repository():
    transport = Transport()
    with pytest.raises(ValueError, match="rollback target|unknown"):
        OperationalCandidateRollbacker(
            targets=targets_for("dripvid", "deployment.rollback"),
            transport=transport,
            repository="other",
        )


def test_operational_rollbacker_rejects_mismatched_target():
    rollbacker, transport = build_rollbacker(
        result={"rolled_back": True, "release_id": RELEASE_ID}
    )

    with pytest.raises(ValueError, match="target"):
        rollbacker.rollback(rollback_target(repository="ai-hq"), release_id=RELEASE_ID)