from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from ai_hq.delivery.repository_profiles import (
    RepositoryProfile,
    RepositoryProfileRegistry,
)
from ai_hq.delivery.repository_workspace import (
    CandidateSnapshot,
    FileChange,
    FileOperation,
    RepositoryWorkspace,
    TestEvidence,
)

_CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_MAX_EVIDENCE_SUMMARY = 4000
_MAX_OUTPUT_PER_STREAM = 1800
_MAX_CANDIDATE_REVIEW_DIFF = 24_000


@dataclass
class _WorkspaceState:
    path: Path
    profile: RepositoryProfile
    base_manifest: dict[str, str]
    snapshot_fingerprint: str | None = None
    candidate_review_diff: str | None = None


class IsolatedRepositorySandbox:
    """Concrete repository workspace boundary with no production authority."""

    def __init__(
        self,
        *,
        profile_registry: RepositoryProfileRegistry,
        repository_key: str,
        sandbox_root: Path,
        command_runner: _CommandRunner | None = None,
    ) -> None:
        self._profile = profile_registry.get(repository_key)
        self._sandbox_root = Path(sandbox_root).expanduser().resolve()
        self._validate_root_isolation()
        self._sandbox_root.mkdir(parents=True, exist_ok=True)
        self._workspaces: dict[str, _WorkspaceState] = {}
        self._command_runner = command_runner or self._run_profile_command

    def prepare(self, *, mission_id: str) -> RepositoryWorkspace:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("mission_id is required")

        workspace_id = str(uuid4())
        workspace_path = self._sandbox_root / workspace_id
        shutil.copytree(
            self._profile.source_path,
            workspace_path,
            symlinks=True,
        )
        base_manifest = self._manifest(workspace_path)
        self._workspaces[workspace_id] = _WorkspaceState(
            path=workspace_path,
            profile=self._profile,
            base_manifest=base_manifest,
        )
        return RepositoryWorkspace(
            mission_id=mission_id,
            repository=self._profile.key,
            base_ref=self._profile.base_ref,
            workspace_id=workspace_id,
        )

    def apply_changes(
        self,
        *,
        workspace: RepositoryWorkspace,
        changes: tuple[FileChange, ...],
    ) -> CandidateSnapshot:
        state = self._state_for(workspace)
        if not isinstance(changes, tuple):
            raise TypeError("changes must be a tuple")

        before: dict[str, str | None] = {}

        for change in changes:
            if not isinstance(change, FileChange):
                raise TypeError(
                    "changes must contain FileChange values"
                )

            target = self._safe_target(
                state.path,
                change.path,
            )

            if change.path not in before:
                before[change.path] = (
                    self._review_text(target)
                )

        for change in changes:
            target = self._safe_target(
                state.path,
                change.path,
            )

            if change.operation is FileOperation.WRITE:
                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                target.write_text(
                    change.content or "",
                    encoding="utf-8",
                )

            elif change.operation is FileOperation.DELETE:
                if target.exists():
                    if (
                        not target.is_file()
                        or target.is_symlink()
                    ):
                        raise ValueError(
                            "delete target must be a "
                            "regular workspace file"
                        )
                    target.unlink()

            else:
                raise ValueError(
                    "unsupported repository file operation"
                )

        after = {
            relative: self._review_text(
                self._safe_target(
                    state.path,
                    relative,
                )
            )
            for relative in before
        }

        state.candidate_review_diff = (
            self._build_review_diff(
                before=before,
                after=after,
            )
        )

        return self.snapshot(
            workspace=workspace
        )

    def snapshot(
        self,
        *,
        workspace: RepositoryWorkspace,
    ) -> CandidateSnapshot:
        state = self._state_for(workspace)
        candidate_manifest = self._manifest(state.path)
        changed_files = tuple(
            sorted(
                path
                for path in set(state.base_manifest) | set(candidate_manifest)
                if state.base_manifest.get(path) != candidate_manifest.get(path)
            )
        )
        diff_material = [
            {
                "path": path,
                "before": state.base_manifest.get(path, "deleted-or-absent"),
                "after": candidate_manifest.get(path, "deleted-or-absent"),
            }
            for path in changed_files
        ]
        content_digest = self._canonical_digest(candidate_manifest)
        state.snapshot_fingerprint = content_digest
        return CandidateSnapshot(
            workspace_id=workspace.workspace_id,
            repository=workspace.repository,
            base_ref=workspace.base_ref,
            changed_files=changed_files,
            diff_digest=self._canonical_digest(diff_material),
            content_digest=content_digest,
        )

    def review_diff(
        self,
        *,
        workspace: RepositoryWorkspace,
    ) -> str:
        state = self._state_for(workspace)

        self._require_current_snapshot(state)

        if state.candidate_review_diff is None:
            raise RuntimeError(
                "candidate review diff is required "
                "before QA"
            )

        return state.candidate_review_diff

    def run_tests(
        self,
        *,
        workspace: RepositoryWorkspace,
    ) -> TestEvidence:
        state = self._state_for(workspace)
        self._require_current_snapshot(state)

        records: list[dict[str, object]] = []
        summary_parts: list[str] = []
        final_exit_code = 0
        passed = True

        for index, command in enumerate(state.profile.test_commands, start=1):
            try:
                result = self._command_runner(
                    command,
                    cwd=state.path,
                    timeout_seconds=state.profile.test_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("repository test profile timed out") from exc

            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            bounded_stdout = stdout[:_MAX_OUTPUT_PER_STREAM]
            bounded_stderr = stderr[:_MAX_OUTPUT_PER_STREAM]
            records.append(
                {
                    "index": index,
                    "returncode": result.returncode,
                    "stdout": bounded_stdout,
                    "stderr": bounded_stderr,
                }
            )

            output = "\n".join(
                part for part in (bounded_stdout, bounded_stderr) if part
            )
            summary = f"step {index}: exit {result.returncode}"
            if output:
                summary += f"\n{output}"
            summary_parts.append(summary)

            if result.returncode != 0:
                passed = False
                final_exit_code = result.returncode
                break

        evidence_summary = "\n\n".join(summary_parts).strip()
        if not evidence_summary:
            evidence_summary = "repository test profile completed"
        evidence_summary = evidence_summary[:_MAX_EVIDENCE_SUMMARY]

        return TestEvidence(
            passed=passed,
            exit_code=final_exit_code,
            summary=evidence_summary,
            evidence_digest=self._canonical_digest(records),
        )

    def _require_current_snapshot(self, state: _WorkspaceState) -> None:
        if state.snapshot_fingerprint is None:
            raise RuntimeError("repository workspace snapshot is required before tests")
        current_fingerprint = self._canonical_digest(self._manifest(state.path))
        if current_fingerprint != state.snapshot_fingerprint:
            raise RuntimeError("repository workspace snapshot is stale")

    @staticmethod
    def _review_text(
        path: Path,
    ) -> str | None:
        if not path.exists():
            return None

        if (
            not path.is_file()
            or path.is_symlink()
        ):
            raise ValueError(
                "candidate review diff requires "
                "regular files"
            )

        try:
            return path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError as exc:
            raise ValueError(
                "candidate review diff requires "
                "UTF-8 text files"
            ) from exc

    @staticmethod
    def _build_review_diff(
        *,
        before: dict[str, str | None],
        after: dict[str, str | None],
    ) -> str:
        sections: list[str] = []

        for relative in sorted(before):
            old = before[relative]
            new = after[relative]

            if old == new:
                continue

            old_lines = (
                []
                if old is None
                else old.splitlines(
                    keepends=True
                )
            )

            new_lines = (
                []
                if new is None
                else new.splitlines(
                    keepends=True
                )
            )

            fromfile = (
                "/dev/null"
                if old is None
                else f"a/{relative}"
            )

            tofile = (
                "/dev/null"
                if new is None
                else f"b/{relative}"
            )

            section = "".join(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=fromfile,
                    tofile=tofile,
                    lineterm="\n",
                )
            )

            sections.append(section)

        review_diff = "".join(
            sections
        )

        if (
            len(review_diff)
            > _MAX_CANDIDATE_REVIEW_DIFF
        ):
            raise ValueError(
                "candidate review diff exceeds "
                "maximum safe review size"
            )

        return review_diff

    @staticmethod
    def _run_profile_command(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

    def _validate_root_isolation(self) -> None:
        source = self._profile.source_path.resolve()
        sandbox = self._sandbox_root
        if source == sandbox or source in sandbox.parents or sandbox in source.parents:
            raise ValueError("repository sandbox must not overlap repository source")

    def _state_for(self, workspace: RepositoryWorkspace) -> _WorkspaceState:
        if not isinstance(workspace, RepositoryWorkspace):
            raise TypeError("workspace must be a RepositoryWorkspace")
        try:
            state = self._workspaces[workspace.workspace_id]
        except KeyError as exc:
            raise KeyError(f"unknown repository workspace: {workspace.workspace_id}") from exc

        if workspace.repository != state.profile.key:
            raise ValueError("workspace repository identity mismatch")
        if workspace.base_ref != state.profile.base_ref:
            raise ValueError("workspace base reference mismatch")
        return state

    def _safe_target(self, workspace_root: Path, raw_path: str) -> Path:
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("repository path is required")
        if "\\" in raw_path:
            raise ValueError("repository path must use normalized relative separators")

        pure_path = PurePosixPath(raw_path)
        raw_parts = raw_path.split("/")
        if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
            raise ValueError("repository path must be normalized and relative to workspace")

        current = workspace_root
        for part in pure_path.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("repository path cannot traverse a symlink escape")

        resolved_parent = current.parent.resolve()
        root = workspace_root.resolve()
        if resolved_parent != root and root not in resolved_parent.parents:
            raise ValueError("repository path escapes workspace")
        return current

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
                    manifest[relative] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

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
