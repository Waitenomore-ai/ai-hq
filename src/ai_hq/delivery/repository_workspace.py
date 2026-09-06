from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

_SHA256_PREFIX = "sha256:"
_SHA256_HEX_LENGTH = 64
_MAX_TEST_SUMMARY_LENGTH = 4000


def _required(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _sha256_digest(value: str, *, field: str) -> str:
    value = _required(value, field=field)
    if not value.startswith(_SHA256_PREFIX):
        raise ValueError(f"{field} must be a sha256 digest")

    digest = value[len(_SHA256_PREFIX) :]
    if len(digest) != _SHA256_HEX_LENGTH:
        raise ValueError(f"{field} must be a sha256 digest")

    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a sha256 digest") from exc

    return value


@dataclass(frozen=True)
class RepositoryWorkspace:
    """Opaque identity for one isolated non-production candidate workspace."""

    mission_id: str
    repository: str
    base_ref: str
    workspace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mission_id",
            _required(self.mission_id, field="mission_id"),
        )
        object.__setattr__(
            self,
            "repository",
            _required(self.repository, field="repository"),
        )
        object.__setattr__(
            self,
            "base_ref",
            _required(self.base_ref, field="base_ref"),
        )
        object.__setattr__(
            self,
            "workspace_id",
            _required(self.workspace_id, field="workspace_id"),
        )


@dataclass(frozen=True)
class CandidateSnapshot:
    """Machine-observed immutable repository candidate identity material."""

    workspace_id: str
    repository: str
    base_ref: str
    changed_files: tuple[str, ...]
    diff_digest: str
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workspace_id",
            _required(self.workspace_id, field="workspace_id"),
        )
        object.__setattr__(
            self,
            "repository",
            _required(self.repository, field="repository"),
        )
        object.__setattr__(
            self,
            "base_ref",
            _required(self.base_ref, field="base_ref"),
        )

        if not isinstance(self.changed_files, tuple):
            raise TypeError("changed_files must be a tuple")

        normalized_files: list[str] = []
        for path in self.changed_files:
            if not isinstance(path, str) or not path.strip():
                raise ValueError(
                    "changed_files must contain non-empty strings"
                )
            normalized_files.append(path.strip())

        object.__setattr__(self, "changed_files", tuple(normalized_files))
        object.__setattr__(
            self,
            "diff_digest",
            _sha256_digest(self.diff_digest, field="diff_digest"),
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_digest(self.content_digest, field="content_digest"),
        )

    def identity_payload(self, *, mission_id: str) -> dict[str, object]:
        return {
            "mission_id": _required(mission_id, field="mission_id"),
            "repository": self.repository,
            "base_ref": self.base_ref,
            "workspace_id": self.workspace_id,
            "changed_files": list(self.changed_files),
            "diff_digest": self.diff_digest,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True)
class TestEvidence:
    """Machine-generated result from the workspace's fixed test profile."""

    passed: bool
    exit_code: int
    summary: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a boolean")
        if not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool):
            raise TypeError("exit_code must be an integer")

        summary = _required(self.summary, field="summary")
        if len(summary) > _MAX_TEST_SUMMARY_LENGTH:
            raise ValueError("summary exceeds maximum length")

        object.__setattr__(self, "summary", summary)
        object.__setattr__(
            self,
            "evidence_digest",
            _sha256_digest(
                self.evidence_digest,
                field="evidence_digest",
            ),
        )


class RepositoryWorkspaceService(Protocol):
    """Narrow repository workspace boundary; deliberately not a shell API."""

    def prepare(self, *, mission_id: str) -> RepositoryWorkspace:
        ...

    def snapshot(
        self,
        *,
        workspace: RepositoryWorkspace,
    ) -> CandidateSnapshot:
        ...

    def run_tests(
        self,
        *,
        workspace: RepositoryWorkspace,
    ) -> TestEvidence:
        ...
