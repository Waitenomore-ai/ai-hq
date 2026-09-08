from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

_ALLOWED_REPOSITORIES = frozenset({"ai-hq", "dripvid"})
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class PersistedCandidate:
    mission_id: str
    repository: str
    workspace_id: str
    base_ref: str
    base_commit: str
    change_ref: str
    changed_files: tuple[str, ...]
    content_digest: str
    workspace_path: Path


class CandidateStore:
    """Reopen a persisted candidate only after machine evidence re-verifies."""

    def __init__(self, sandbox_root: Path) -> None:
        root = Path(sandbox_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("candidate sandbox root must be an existing directory")
        self._sandbox_root = root

    def load_verified(
        self,
        *,
        mission_id: str,
        change_ref: str,
        changed_files: tuple[str, ...] | list[str],
        evidence: Mapping[str, Any],
    ) -> PersistedCandidate:
        mission = self._required(mission_id, "mission_id")
        requested_ref = self._sha256(change_ref, "change_ref")
        if not isinstance(evidence, Mapping):
            raise TypeError("evidence must be a mapping")
        if evidence.get("verification") != "candidate_identity_verified":
            raise ValueError("candidate verification evidence is required")
        if evidence.get("algorithm") not in {None, "sha256"}:
            raise ValueError("candidate verification algorithm is invalid")

        evidence_ref = self._sha256(evidence.get("change_ref"), "change_ref")
        if evidence_ref != requested_ref:
            raise ValueError("candidate change_ref mismatch")

        repository = self._required(evidence.get("repository"), "repository")
        if repository not in _ALLOWED_REPOSITORIES:
            raise ValueError("unknown candidate repository")

        base_ref = self._required(evidence.get("base_ref"), "base_ref")
        if base_ref != "main":
            raise ValueError("candidate base reference must be main")

        base_commit = self._git_commit(evidence.get("base_commit"))
        workspace_id = self._workspace_id(evidence.get("workspace_id"))
        diff_digest = self._sha256(evidence.get("diff_digest"), "diff_digest")
        content_digest = self._sha256(
            evidence.get("content_digest"),
            "content_digest",
        )
        normalized_files = self._changed_files(changed_files)

        identity = {
            "mission_id": mission,
            "repository": repository,
            "base_ref": base_ref,
            "base_commit": base_commit,
            "workspace_id": workspace_id,
            "changed_files": list(normalized_files),
            "diff_digest": diff_digest,
            "content_digest": content_digest,
        }
        if self._canonical_digest(identity) != requested_ref:
            raise ValueError("candidate change_ref does not match machine identity")

        repository_root = self._sandbox_root / repository
        workspace_path = repository_root / workspace_id
        if workspace_path.is_symlink():
            raise ValueError("candidate workspace cannot be a symlink")
        if not workspace_path.is_dir():
            raise ValueError("candidate workspace is missing")

        resolved_repository = repository_root.resolve()
        resolved_workspace = workspace_path.resolve()
        if (
            resolved_workspace.parent != resolved_repository
            or resolved_repository.parent != self._sandbox_root
        ):
            raise ValueError("candidate workspace escapes sandbox root")

        current_digest = self._canonical_digest(self._manifest(resolved_workspace))
        if current_digest != content_digest:
            raise ValueError("candidate workspace content digest is stale")

        return PersistedCandidate(
            mission_id=mission,
            repository=repository,
            workspace_id=workspace_id,
            base_ref=base_ref,
            base_commit=base_commit,
            change_ref=requested_ref,
            changed_files=normalized_files,
            content_digest=content_digest,
            workspace_path=resolved_workspace,
        )

    def read_changed_file(
        self,
        candidate: PersistedCandidate,
        path: str,
    ) -> bytes | None:
        if not isinstance(candidate, PersistedCandidate):
            raise TypeError("candidate must be a PersistedCandidate")
        relative = self._safe_changed_path(path)
        if relative not in candidate.changed_files:
            raise ValueError("path is not a verified changed file")

        target = candidate.workspace_path / PurePosixPath(relative)
        if target.is_symlink():
            raise ValueError("changed file must be a regular file, not a symlink")
        if not target.exists():
            return None
        if not target.is_file():
            raise ValueError("changed file must be a regular file")

        resolved_parent = target.parent.resolve()
        root = candidate.workspace_path.resolve()
        if resolved_parent != root and root not in resolved_parent.parents:
            raise ValueError("changed file escapes candidate workspace")
        return target.read_bytes()

    @classmethod
    def _changed_files(
        cls,
        values: tuple[str, ...] | list[str],
    ) -> tuple[str, ...]:
        if not isinstance(values, (tuple, list)):
            raise TypeError("changed_files must be a list or tuple")
        normalized = tuple(cls._safe_changed_path(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("changed file paths must be unique")
        if tuple(sorted(normalized)) != normalized:
            raise ValueError("changed file paths must be sorted")
        return normalized

    @staticmethod
    def _safe_changed_path(value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("changed file path is required")
        if "\\" in value:
            raise ValueError("changed file path must use normalized separators")
        pure = PurePosixPath(value)
        parts = value.split("/")
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("changed file path must be normalized and relative")
        if parts[0] == ".git":
            raise ValueError("changed file path cannot target .git")
        return pure.as_posix()

    @staticmethod
    def _workspace_id(value: Any) -> str:
        value = CandidateStore._required(value, "workspace_id")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("workspace_id must be a UUID") from exc
        normalized = str(parsed)
        if normalized != value:
            raise ValueError("workspace_id must be a normalized UUID")
        return normalized

    @staticmethod
    def _git_commit(value: Any) -> str:
        value = CandidateStore._required(value, "base_commit")
        if not _GIT_COMMIT_RE.fullmatch(value):
            raise ValueError("base_commit must be a 40-character lowercase Git commit")
        return value

    @staticmethod
    def _sha256(value: Any, field: str) -> str:
        value = CandidateStore._required(value, field)
        if not _SHA256_RE.fullmatch(value):
            raise ValueError(f"{field} must be a sha256 digest")
        return value

    @staticmethod
    def _required(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is required")
        return value.strip()

    @staticmethod
    def _manifest(root: Path) -> dict[str, str]:
        manifest: dict[str, str] = {}
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            relative_directory = directory_path.relative_to(root)
            if relative_directory.parts and relative_directory.parts[0] == ".git":
                dirnames[:] = []
                continue
            dirnames[:] = [name for name in dirnames if name != ".git"]

            for name in filenames:
                path = directory_path / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    manifest[relative] = f"symlink:{os.readlink(path)}"
                    continue
                if path.is_file():
                    manifest[relative] = "sha256:" + hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()

            for name in dirnames:
                path = directory_path / name
                if path.is_symlink():
                    relative = path.relative_to(root).as_posix()
                    manifest[relative] = f"symlink:{os.readlink(path)}"
        return manifest

    @staticmethod
    def _canonical_digest(value: object) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
