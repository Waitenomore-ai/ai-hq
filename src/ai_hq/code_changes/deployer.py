from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ai_hq.code_changes.publisher import PublishedCandidate
from ai_hq.delivery.repository_profiles import TRUSTED_REPOSITORY_KEYS
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
class DeployedRelease:
    repository: str
    change_ref: str
    release_id: str
    prior_release_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or self.repository not in {
            "ai-hq",
            "dripvid",
        }:
            raise ValueError("unknown deployed repository")
        if not isinstance(self.change_ref, str) or not _SHA256_RE.fullmatch(
            self.change_ref
        ):
            raise ValueError("change_ref must be a sha256 digest")
        if not isinstance(self.release_id, str) or not _release_id_valid(
            self.release_id
        ):
            raise ValueError("release id must use the trusted release identity charset")
        if (
            self.prior_release_id is not None
            and not _release_id_valid(self.prior_release_id)
        ):
            raise ValueError(
                "prior release id must use the trusted release identity charset"
            )


class CandidateDeployer(Protocol):
    def deploy(self, candidate: PublishedCandidate) -> DeployedRelease:
        ...


class OperationalCandidateDeployer:
    """Deploy one already-published candidate through the existing operation transport.

    Fail-closed guarantees:
      - the target must exist and explicitly allow ``deployment.deploy``;
      - the transport result must carry a trusted ``release_id`` (and optional
        ``prior_release_id``) that round-trips the trusted identity charset;
      - the returned ``DeployedRelease`` must match the exact published candidate.

    This adapter never invents identity, never accepts model-supplied release ids
    or paths, and never enables deployment on its own: callers must construct it
    with a target/transport that actually grants the capability.
    """

    def __init__(
        self,
        *,
        targets: OperationalTargetRegistry,
        transport: OperationalTransport,
        repository: str,
    ) -> None:
        if not isinstance(repository, str) or repository not in TRUSTED_REPOSITORY_KEYS:
            raise ValueError("unsupported deploy target")
        try:
            target = targets.require(repository)
        except ValueError:
            raise ValueError("unknown deploy target") from None
        if not target.allows("deployment.deploy"):
            raise ValueError("deployment.deploy is not granted for this target")
        method = getattr(transport, "deployment_deploy", None)
        if method is None:
            raise ValueError("deployment transport is unavailable")
        self._target: OperationalTarget = target
        self._transport = transport

    def deploy(self, candidate: PublishedCandidate) -> DeployedRelease:
        if not isinstance(candidate, PublishedCandidate):
            raise TypeError("candidate must be a PublishedCandidate")
        if candidate.repository != self._target.key:
            raise ValueError("candidate repository does not match deploy target")

        result = self._transport.deployment_deploy(self._target)
        if not isinstance(result, dict):
            raise RuntimeError("deployment adapter returned an invalid result")
        if result.get("deployed") is not True:
            raise RuntimeError("deployment adapter did not confirm deployment")

        release_id = result.get("release_id")
        if not isinstance(release_id, str) or not _release_id_valid(release_id):
            raise RuntimeError("deployment adapter returned no trusted release id")

        prior_release_id = result.get("prior_release_id")
        if prior_release_id is not None:
            if not isinstance(prior_release_id, str) or not _release_id_valid(
                prior_release_id
            ):
                raise RuntimeError(
                    "deployment adapter returned no trusted prior release id"
                )

        return DeployedRelease(
            repository=candidate.repository,
            change_ref=candidate.change_ref,
            release_id=release_id,
            prior_release_id=prior_release_id,
        )