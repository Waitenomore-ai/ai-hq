from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from ai_hq.code_changes.candidate_store import CandidateStore, PersistedCandidate
from ai_hq.delivery.repository_profiles import TRUSTED_REPOSITORY_KEYS

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_PREFIX_RE = re.compile(r"^[A-Za-z0-9._/-]+/$")
_ALLOWED_BLOB_MODES = {"100644", "100755"}


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

        if key not in TRUSTED_REPOSITORY_KEYS:
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
        if repository not in TRUSTED_REPOSITORY_KEYS:
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


class GitHubCandidatePublisher:
    """Publish one already-verified sandbox candidate to a generated GitHub ref."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        token: str,
        candidate_store: CandidateStore,
        targets: RepositoryPublishTargetRegistry,
    ) -> None:
        if not isinstance(http_client, httpx.Client):
            raise TypeError("http_client must be an httpx.Client")
        self._token = _required(token, "token")
        self._http = http_client
        self._store = candidate_store
        self._targets = targets

    def publish(self, candidate: PersistedCandidate) -> PublishedCandidate:
        if not isinstance(candidate, PersistedCandidate):
            raise TypeError("candidate must be a PersistedCandidate")
        if candidate.base_commit == "0" * 40 or not _GIT_SHA_RE.fullmatch(
            candidate.base_commit
        ):
            raise ValueError("candidate base commit must be an exact Git commit")

        target = self._targets.get(candidate.repository)
        root = f"https://api.github.com/repos/{target.repository_full_name}"

        ref = self._request("GET", f"{root}/git/ref/heads/{target.base_branch}")
        remote_base = _git_sha(ref.get("object", {}).get("sha"), "remote base")
        if remote_base != candidate.base_commit:
            raise RuntimeError("candidate base is stale; remote main has changed")

        commit = self._request("GET", f"{root}/git/commits/{candidate.base_commit}")
        base_tree = _git_sha(commit.get("tree", {}).get("sha"), "base tree")
        tree = self._request("GET", f"{root}/git/trees/{base_tree}?recursive=1")
        if tree.get("truncated") is True:
            raise RuntimeError("GitHub base tree is truncated")

        base_entries: dict[str, dict[str, object]] = {}
        for entry in tree.get("tree", []):
            if not isinstance(entry, dict):
                raise RuntimeError("GitHub base tree is invalid")
            path = entry.get("path")
            mode = entry.get("mode")
            entry_type = entry.get("type")
            if not isinstance(path, str):
                raise RuntimeError("GitHub base tree path is invalid")
            if entry_type == "tree":
                if mode != "040000":
                    raise RuntimeError("GitHub base tree contains invalid directory mode")
                continue
            if mode in {"120000", "160000"}:
                raise RuntimeError("GitHub base tree contains unsupported symlink or submodule entry")
            if entry_type != "blob":
                raise RuntimeError("GitHub base tree contains unsupported non-blob entry")
            if mode not in _ALLOWED_BLOB_MODES:
                raise RuntimeError("GitHub base tree contains unsupported blob mode")
            base_entries[path] = entry

        changes: list[dict[str, object]] = []
        for path in sorted(candidate.changed_files):
            content = self._store.read_changed_file(candidate, path)
            existing = base_entries.get(path)
            mode = existing.get("mode") if existing is not None else "100644"
            if mode not in _ALLOWED_BLOB_MODES:
                raise RuntimeError("candidate file has unsupported Git mode")

            if content is None:
                if existing is None:
                    raise RuntimeError("verified deletion is absent from base tree")
                blob_sha: str | None = None
            else:
                blob = self._request(
                    "POST",
                    f"{root}/git/blobs",
                    json={
                        "content": base64.b64encode(content).decode("ascii"),
                        "encoding": "base64",
                    },
                )
                blob_sha = _git_sha(blob.get("sha"), "blob")

            changes.append(
                {
                    "path": path,
                    "mode": mode,
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        new_tree = self._request(
            "POST",
            f"{root}/git/trees",
            json={"base_tree": base_tree, "tree": changes},
        )
        tree_sha = _git_sha(new_tree.get("sha"), "published tree")

        new_commit = self._request(
            "POST",
            f"{root}/git/commits",
            json={
                "message": f"AI HQ verified candidate {candidate.change_ref[:19]}",
                "tree": tree_sha,
                "parents": [candidate.base_commit],
            },
        )
        commit_sha = _git_sha(new_commit.get("sha"), "published commit")
        returned_tree = new_commit.get("tree")
        if isinstance(returned_tree, dict):
            returned_tree_sha = _git_sha(returned_tree.get("sha"), "published commit tree")
            if returned_tree_sha != tree_sha:
                raise RuntimeError("GitHub published commit tree mismatch")

        branch_name = generated_branch_name(
            target,
            mission_id=candidate.mission_id,
            change_ref=candidate.change_ref,
        )
        created_ref = self._request(
            "POST",
            f"{root}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": commit_sha},
        )
        created_sha = _git_sha(created_ref.get("object", {}).get("sha"), "published ref")
        if created_sha != commit_sha:
            raise RuntimeError("GitHub published ref commit mismatch")

        return PublishedCandidate(
            repository=candidate.repository,
            change_ref=candidate.change_ref,
            branch_name=branch_name,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            base_commit=candidate.base_commit,
        )

    def _request(self, method: str, url: str, **kwargs) -> dict[str, object]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            response = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise RuntimeError("GitHub candidate publication request failed") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError("GitHub candidate publication request failed")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("GitHub candidate publication returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub candidate publication returned invalid payload")
        return payload


def _git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA_RE.fullmatch(value):
        raise RuntimeError(f"GitHub {field} identity is invalid")
    return value


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()
