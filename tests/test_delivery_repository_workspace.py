from dataclasses import FrozenInstanceError

import pytest

from ai_hq.delivery.repository_workspace import (
    CandidateSnapshot,
    FileChange,
    FileOperation,
    RepositoryWorkspace,
    RepositoryWorkspaceService,
)
from ai_hq.delivery.repository_workspace import (
    TestEvidence as WorkspaceTestEvidence,
)


def test_repository_workspace_is_immutable_and_validated():
    workspace = RepositoryWorkspace(
        mission_id="mission-1",
        repository="Waitenomore-ai/ai-hq",
        base_ref="abc123",
        workspace_id="workspace-1",
    )

    with pytest.raises(FrozenInstanceError):
        workspace.workspace_id = "changed"

    with pytest.raises(ValueError, match="mission_id"):
        RepositoryWorkspace(
            mission_id="",
            repository="Waitenomore-ai/ai-hq",
            base_ref="abc123",
            workspace_id="workspace-1",
        )


def test_candidate_snapshot_identity_payload_is_machine_observed():
    snapshot = CandidateSnapshot(
        workspace_id="workspace-1",
        repository="Waitenomore-ai/ai-hq",
        base_ref="abc123",
        changed_files=("src/a.py", "tests/test_a.py"),
        diff_digest="sha256:" + ("a" * 64),
        content_digest="sha256:" + ("b" * 64),
    )

    assert snapshot.identity_payload(mission_id="mission-1") == {
        "mission_id": "mission-1",
        "repository": "Waitenomore-ai/ai-hq",
        "base_ref": "abc123",
        "workspace_id": "workspace-1",
        "changed_files": ["src/a.py", "tests/test_a.py"],
        "diff_digest": "sha256:" + ("a" * 64),
        "content_digest": "sha256:" + ("b" * 64),
    }


def test_candidate_snapshot_rejects_invalid_digests_and_file_types():
    with pytest.raises(ValueError, match="diff_digest"):
        CandidateSnapshot(
            workspace_id="workspace-1",
            repository="Waitenomore-ai/ai-hq",
            base_ref="abc123",
            changed_files=("src/a.py",),
            diff_digest="not-a-digest",
            content_digest="sha256:" + ("b" * 64),
        )

    with pytest.raises(ValueError, match="changed_files"):
        CandidateSnapshot(
            workspace_id="workspace-1",
            repository="Waitenomore-ai/ai-hq",
            base_ref="abc123",
            changed_files=("",),
            diff_digest="sha256:" + ("a" * 64),
            content_digest="sha256:" + ("b" * 64),
        )


def test_test_evidence_is_immutable_bounded_and_validated():
    evidence = WorkspaceTestEvidence(
        passed=True,
        exit_code=0,
        summary="42 passed",
        evidence_digest="sha256:" + ("c" * 64),
    )

    with pytest.raises(FrozenInstanceError):
        evidence.exit_code = 1

    with pytest.raises(ValueError, match="summary"):
        WorkspaceTestEvidence(
            passed=False,
            exit_code=1,
            summary="x" * 4001,
            evidence_digest="sha256:" + ("c" * 64),
        )


def test_file_change_is_immutable_and_write_requires_content():
    change = FileChange(
        path="src/example.py",
        operation=FileOperation.WRITE,
        content="print('ok')\n",
    )

    with pytest.raises(FrozenInstanceError):
        change.path = "other.py"

    with pytest.raises(ValueError, match="content"):
        FileChange(path="src/example.py", operation=FileOperation.WRITE)


def test_delete_rejects_content():
    with pytest.raises(ValueError, match="content"):
        FileChange(
            path="src/example.py",
            operation=FileOperation.DELETE,
            content="not allowed",
        )


def test_workspace_service_protocol_exposes_typed_changes_not_shell():
    names = set(dir(RepositoryWorkspaceService))

    assert "apply_changes" in names

    forbidden = {
        "run",
        "execute",
        "execute_shell",
        "shell",
        "command",
    }
    assert forbidden.isdisjoint(names)
