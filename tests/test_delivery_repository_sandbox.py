import inspect
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
)
from ai_hq.delivery.repository_sandbox import IsolatedRepositorySandbox
from ai_hq.delivery.repository_workspace import FileChange, FileOperation


def build_sandbox(tmp_path, *, command_runner=None):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "original.py").write_text("VALUE = 1\n")
    (source / "delete_me.txt").write_text("remove me\n")

    sandbox_root = tmp_path / "sandbox"
    registry = RepositoryProfileRegistry(
        (build_ai_hq_repository_profile(source_path=source),)
    )
    kwargs = {}
    if command_runner is not None:
        kwargs["command_runner"] = command_runner
    sandbox = IsolatedRepositorySandbox(
        profile_registry=registry,
        repository_key="ai-hq",
        sandbox_root=sandbox_root,
        **kwargs,
    )
    return sandbox, source, sandbox_root


def only_workspace_path(sandbox_root: Path) -> Path:
    paths = list(sandbox_root.iterdir())
    assert len(paths) == 1
    return paths[0]


def test_prepare_copies_source_into_disposable_sandbox_workspace(tmp_path):
    sandbox, source, sandbox_root = build_sandbox(tmp_path)

    workspace = sandbox.prepare(mission_id="mission-1")
    workspace_path = only_workspace_path(sandbox_root)

    assert workspace.repository == "ai-hq"
    assert workspace.mission_id == "mission-1"
    assert workspace.workspace_id == workspace_path.name
    assert workspace_path.parent == sandbox_root.resolve()
    assert (workspace_path / "src" / "original.py").read_text() == "VALUE = 1\n"
    assert (source / "src" / "original.py").read_text() == "VALUE = 1\n"


def test_apply_changes_writes_nested_file_only_inside_workspace(tmp_path):
    sandbox, source, sandbox_root = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")

    snapshot = sandbox.apply_changes(
        workspace=workspace,
        changes=(
            FileChange(
                path="src/nested/new.py",
                operation=FileOperation.WRITE,
                content="VALUE = 2\n",
            ),
        ),
    )
    workspace_path = only_workspace_path(sandbox_root)

    assert (workspace_path / "src" / "nested" / "new.py").read_text() == "VALUE = 2\n"
    assert not (source / "src" / "nested" / "new.py").exists()
    assert snapshot.changed_files == ("src/nested/new.py",)


def test_apply_changes_deletes_only_workspace_file(tmp_path):
    sandbox, source, sandbox_root = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")

    snapshot = sandbox.apply_changes(
        workspace=workspace,
        changes=(
            FileChange(
                path="delete_me.txt",
                operation=FileOperation.DELETE,
            ),
        ),
    )
    workspace_path = only_workspace_path(sandbox_root)

    assert not (workspace_path / "delete_me.txt").exists()
    assert (source / "delete_me.txt").read_text() == "remove me\n"
    assert snapshot.changed_files == ("delete_me.txt",)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../escape.py",
        "src/../../escape.py",
    ],
)
def test_apply_changes_rejects_paths_that_escape_workspace(tmp_path, path):
    sandbox, _, _ = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")

    with pytest.raises(ValueError, match="workspace|relative|escape"):
        sandbox.apply_changes(
            workspace=workspace,
            changes=(
                FileChange(
                    path=path,
                    operation=FileOperation.WRITE,
                    content="blocked\n",
                ),
            ),
        )


def test_apply_changes_rejects_symlink_escape(tmp_path):
    sandbox, source, _ = build_sandbox(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.txt").write_text("safe\n")
    (source / "escape").symlink_to(outside, target_is_directory=True)

    workspace = sandbox.prepare(mission_id="mission-1")

    with pytest.raises(ValueError, match="symlink|escape"):
        sandbox.apply_changes(
            workspace=workspace,
            changes=(
                FileChange(
                    path="escape/target.txt",
                    operation=FileOperation.WRITE,
                    content="unsafe\n",
                ),
            ),
        )

    assert (outside / "target.txt").read_text() == "safe\n"


def test_unknown_workspace_fails_closed(tmp_path):
    sandbox, _, _ = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")
    unknown = type(workspace)(
        mission_id=workspace.mission_id,
        repository=workspace.repository,
        base_ref=workspace.base_ref,
        workspace_id="unknown-workspace",
    )

    with pytest.raises(KeyError, match="workspace"):
        sandbox.apply_changes(
            workspace=unknown,
            changes=(
                FileChange(
                    path="src/new.py",
                    operation=FileOperation.WRITE,
                    content="VALUE = 2\n",
                ),
            ),
        )


def test_snapshot_is_deterministic_for_identical_workspace_state(tmp_path):
    sandbox, _, _ = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")
    sandbox.apply_changes(
        workspace=workspace,
        changes=(
            FileChange(
                path="src/new.py",
                operation=FileOperation.WRITE,
                content="VALUE = 2\n",
            ),
        ),
    )

    first = sandbox.snapshot(workspace=workspace)
    second = sandbox.snapshot(workspace=workspace)

    assert first == second
    assert first.changed_files == ("src/new.py",)


def test_snapshot_digests_change_when_workspace_content_changes(tmp_path):
    sandbox, _, _ = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")

    first = sandbox.apply_changes(
        workspace=workspace,
        changes=(
            FileChange(
                path="src/original.py",
                operation=FileOperation.WRITE,
                content="VALUE = 2\n",
            ),
        ),
    )
    second = sandbox.apply_changes(
        workspace=workspace,
        changes=(
            FileChange(
                path="src/original.py",
                operation=FileOperation.WRITE,
                content="VALUE = 3\n",
            ),
        ),
    )

    assert first.diff_digest != second.diff_digest
    assert first.content_digest != second.content_digest


def test_run_tests_rejects_workspace_changed_after_snapshot(tmp_path):
    sandbox, _, sandbox_root = build_sandbox(tmp_path)
    workspace = sandbox.prepare(mission_id="mission-1")
    sandbox.snapshot(workspace=workspace)

    workspace_path = only_workspace_path(sandbox_root)
    (workspace_path / "src" / "original.py").write_text("MUTATED = True\n")

    with pytest.raises(RuntimeError, match="stale"):
        sandbox.run_tests(workspace=workspace)


def test_run_tests_uses_only_fixed_profile_commands(tmp_path):
    calls = []

    def runner(argv, *, cwd, timeout_seconds):
        calls.append((tuple(argv), cwd, timeout_seconds))
        return CompletedProcess(argv, 0, stdout="passed\n", stderr="")

    sandbox, _, sandbox_root = build_sandbox(tmp_path, command_runner=runner)
    workspace = sandbox.prepare(mission_id="mission-1")
    sandbox.snapshot(workspace=workspace)

    evidence = sandbox.run_tests(workspace=workspace)

    assert evidence.passed is True
    assert evidence.exit_code == 0
    assert len(calls) == 2
    assert calls[0][0][1:4] == ("-m", "ruff", "check")
    assert calls[1][0][1:3] == ("-m", "pytest")
    assert all(call[1] == only_workspace_path(sandbox_root) for call in calls)


def test_run_tests_stops_on_first_fixed_command_failure(tmp_path):
    calls = []

    def runner(argv, *, cwd, timeout_seconds):
        calls.append(tuple(argv))
        return CompletedProcess(argv, 1, stdout="", stderr="lint failed\n")

    sandbox, _, _ = build_sandbox(tmp_path, command_runner=runner)
    workspace = sandbox.prepare(mission_id="mission-1")
    sandbox.snapshot(workspace=workspace)

    evidence = sandbox.run_tests(workspace=workspace)

    assert evidence.passed is False
    assert evidence.exit_code == 1
    assert len(calls) == 1
    assert "lint failed" in evidence.summary


def test_run_tests_bounds_machine_evidence_summary(tmp_path):
    def runner(argv, *, cwd, timeout_seconds):
        return CompletedProcess(argv, 0, stdout="x" * 10000, stderr="")

    sandbox, _, _ = build_sandbox(tmp_path, command_runner=runner)
    workspace = sandbox.prepare(mission_id="mission-1")
    sandbox.snapshot(workspace=workspace)

    evidence = sandbox.run_tests(workspace=workspace)

    assert evidence.passed is True
    assert 0 < len(evidence.summary) <= 4000
    assert evidence.evidence_digest.startswith("sha256:")


def test_run_tests_timeout_fails_closed(tmp_path):
    def runner(argv, *, cwd, timeout_seconds):
        raise TimeoutExpired(argv, timeout_seconds)

    sandbox, _, _ = build_sandbox(tmp_path, command_runner=runner)
    workspace = sandbox.prepare(mission_id="mission-1")
    sandbox.snapshot(workspace=workspace)

    with pytest.raises(RuntimeError, match="timed out"):
        sandbox.run_tests(workspace=workspace)


def test_run_tests_public_api_accepts_no_command_input(tmp_path):
    sandbox, _, _ = build_sandbox(tmp_path)

    signature = inspect.signature(sandbox.run_tests)

    assert set(signature.parameters) == {"workspace"}
