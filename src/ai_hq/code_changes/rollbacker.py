from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ai_hq.operations.adapters import OperationalTransport
from ai_hq.operations.targets import OperationalTarget, OperationalTargetRegistry

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _release_id_valid(release_id: str) -> bool:
    if len(release_id) > 128:
        return False
    if not release_id.isascii():
        return False
    return _RELEASE_ID_RE.fullmatch(release_id) is not None


@dataclass(frozen=True)
class RollbackTarget:
    repository: str
    change_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or self.repository not in {
            "ai-hq",
            "dripvid",
        }:
            raise ValueError("unknown rollback repository")
        if not isinstance(self.change_ref, str) or not _SHA256_RE.fullmatch(
            self.change_ref
        ):
            raise ValueError("change_ref must be a sha256 digest")


@dataclass(frozen=True)
class RolledBackRelease:
    repository: str
    change_ref: str
    release_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or self.repository not in {
            "ai-hq",
            "dripvid",
        }:
            raise ValueError("unknown rollback repository")
        if not isinstance(self.change_ref, str) or not _SHA256_RE.fullmatch(
            self.change_ref
        ):
            raise ValueError("change_ref must be a sha256 digest")
        if not isinstance(self.release_id, str) or not _release_id_valid(
            self.release_id
        ):
            raise ValueError("release id must use the trusted release identity charset")


class CandidateRollbacker(Protocol):
    def rollback(
        self,
        target: RollbackTarget,
        *,
        release_id: str,
    ) -> RolledBackRelease:
        ...


class OperationalCandidateRollbacker:
    """Roll back one already-deployed candidate through the existing operation transport.

    Fail-closed guarantees:
      - the target must exist and explicitly allow ``deployment.rollback``;
      - the restored ``release_id`` is supplied by the trusted delivery history
        and must round-trip the trusted identity charset;
      - the transport result must confirm ``rolled_back`` and carry the exact
        same trusted ``release_id``; any fabricated/missing/mismatched identity
        fails closed.

    This adapter never invents identity and never enables rollback on its own:
    callers must construct it with a target/transport that actually grants the
    capability.
    """

    def __init__(
        self,
        *,
        targets: OperationalTargetRegistry,
        transport: OperationalTransport,
        repository: str,
    ) -> None:
        if not isinstance(repository, str) or repository not in {"ai-hq", "dripvid"}:
            raise ValueError("unsupported rollback target")
        try:
            target = targets.require(repository)
        except ValueError:
            raise ValueError("unknown rollback target") from None
        if not target.allows("deployment.rollback"):
            raise ValueError("deployment.rollback is not granted for this target")
        method = getattr(transport, "deployment_rollback", None)
        if method is None:
            raise ValueError("rollback transport is unavailable")
        self._target: OperationalTarget = target
        self._transport = transport

    def rollback(
        self,
        target: RollbackTarget,
        *,
        release_id: str,
    ) -> RolledBackRelease:
        if not isinstance(target, RollbackTarget):
            raise TypeError("target must be a RollbackTarget")
        if target.repository != self._target.key:
            raise ValueError("rollback target does not match transport target")
        if not isinstance(release_id, str) or not _release_id_valid(release_id):
            raise ValueError("release id must use the trusted release identity charset")

        result = self._transport.deployment_rollback(self._target, release_id)
        if not isinstance(result, dict):
            raise RuntimeError("rollback adapter returned an invalid result")
        if result.get("rolled_back") is not True:
            raise RuntimeError("rollback adapter did not confirm rollback")

        confirmed = result.get("release_id")
        if not isinstance(confirmed, str) or not _release_id_valid(confirmed):
            raise RuntimeError("rollback adapter returned no trusted release id")
        if confirmed != release_id:
            raise RuntimeError("rollback adapter confirmed a different release id")

        return RolledBackRelease(
            repository=target.repository,
            change_ref=target.change_ref,
            release_id=confirmed,
        )