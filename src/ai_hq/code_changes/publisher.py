from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from ai_hq.code_changes.candidate_store import PersistedCandidate

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_PREFIX_RE = re.compile(r"^[A-Za-z0-9._/-]+/$")


@dataclass(frozen=True)
class RepositoryPublishTarget:
    key: str
    repository_full_name: str
    base_branch: str
    branch_prefix: str

    def __post_init__(self) -> None:
        key = _required(self.key, "key")
        repository = _required(self.repository_full_name, "repository_full_name")
        base_branch = _required(self.base_branch, "base_branch")
        branch_prefix = _required(self.branch_prefix, "branch_prefix")

        if key not in {"ai-hq", "dripvid"}:
            raise ValueError("unsupported publish target key")
        if not _REPOSITORY_RE.fullmatch(repository):
            raise ValueError("repository_full_name must be owner/name")
        if base_branch != "main":
            raise ValueError("publish target base branch must be main")
        if not _BRANCH_PREFIX_RE.fullmatch(branch_prefix):
            raise ValueError("branch_prefix is invalid")
        if ".." in branch_prefix or branch_prefix.startswith("/"):
            raise ValueError("branch_prefix is invalid")

        object.__setattr__(self, "key", key)
        object.__setattr__(self, "repository_full_name", repository)
        object.__setattr__(self, "base_branch", base_branch)
        object.__setattr__(self, "branch_prefix", branch_prefix)


class RepositoryPublishTargetRegistry:
    def __init__(self, targets: tuple[RepositoryPublishTarget, ...]) -> None:
        if not isinstance(targets, tuple) or not targets:
            raise ValueError("publish targets must be a non-empty tuple")
        by_key: dict[str, RepositoryPublishTarget] = {}
        for target in targets:
            if not isinstance(target, RepositoryPublishTarget):
                raise TypeError("publish targets must contain RepositoryPublishTarget")
            if target.key in by_key:
                raise ValueError(f"duplicate publish target: {target.key}")
            by_key[target.key] = target
        self._targets = by_key

    def get(self, key: str) -> RepositoryPublishTarget:
        try:
            return self._targets[key]
        except KeyError as exc:
            raise KeyError(f"unknown publish target: {key}") from exc


def build_default_publish_targets() -> RepositoryPublishTargetRegistry:
    return RepositoryPublishTargetRegistry(
        (
            RepositoryPublishTarget(
                key="ai-hq",
                repository_full_name="Waitenomore-ai/ai-hq",
                base_branch="main",
                branch_prefix="ai-hq/candidate/",
            ),
            RepositoryPublishTarget(
                key="dripvid",
                repository_full_name="Waitenomore-ai/dripvid",
                base_branch="main",
                branch_prefix="ai-hq/candidate/",
            ),
        )
    )


def generated_branch_name(
    target: RepositoryPublishTarget,
    *,
    mission_id: str,
    change_ref: str,
) -> str:
    if not isinstance(target, RepositoryPublishTarget):
        raise TypeError("target must be a RepositoryPublishTarget")
    mission = _required(mission_id, "mission_id")
    if not isinstance(change_ref, str) or not _SHA256_RE.fullmatch(change_ref):
        raise ValueError("change_ref must be a sha256 digest")
    mission_digest = hashlib.sha256(mission.encode("utf-8")).hexdigest()[:12]
    change_digest = change_ref.split(":", 1)[1][:12]
    return f"{target.branch_prefix}{mission_digest}-{change_digest}"


@dataclass(frozen=True)
class PublishedCandidate:
    repository: str
    change_ref: str
    branch_name: str
    commit_sha: str
    tree_sha: str
    base_commit: str

    def __post_init__(self) -> None:
        repository = _required(self.repository, "repository")
        branch_name = _required(self.branch_name, "branch_name")
        if repository not in {"ai-hq", "dripvid"}:
            raise ValueError("unknown published repository")
        if not isinstance(self.change_ref, str) or not _SHA256_RE.fullmatch(
            self.change_ref
        ):
            raise ValueError("change_ref must be a sha256 digest")
        for field, value in (
            ("commit_sha", self.commit_sha),
            ("tree_sha", self.tree_sha),
            ("base_commit", self.base_commit),
        ):
            if not isinstance(value, str) or not _GIT_SHA_RE.fullmatch(value):
                raise ValueError(f"{field} must be a 40-character Git commit identity")
        if not branch_name.startswith("ai-hq/candidate/"):
            raise ValueError("published branch must use generated candidate namespace")
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "branch_name", branch_name)


class CandidatePublisher(Protocol):
    def publish(self, candidate: PersistedCandidate) -> PublishedCandidate:
        ...


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()
