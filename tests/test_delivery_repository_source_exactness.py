import subprocess

import pytest

from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
)
from ai_hq.delivery.repository_sandbox import IsolatedRepositorySandbox


def git(source, *args):
    return subprocess.run(
        ["git", *args],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )


def build_git_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "app.py").write_text("VALUE = 1\n")
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "AI HQ Tests")
    git(source, "config", "user.email", "ai-hq-tests@example.invalid")
    git(source, "add", ".")
    git(source, "commit", "-m", "base")

    profile = build_ai_hq_repository_profile(
        source_path=source,
        base_ref="main",
    )
    sandbox = IsolatedRepositorySandbox(
        profile_registry=RepositoryProfileRegistry((profile,)),
        repository_key="ai-hq",
        sandbox_root=tmp_path / "sandboxes",
    )
    return source, sandbox


def test_prepare_rejects_dirty_tracked_source_checkout(tmp_path):
    source, sandbox = build_git_source(tmp_path)
    (source / "src" / "app.py").write_text("DIRTY = True\n")

    with pytest.raises(RuntimeError, match="clean|checkout|base"):
        sandbox.prepare(mission_id="dirty-source")


def test_prepare_rejects_source_head_that_is_not_base_commit(tmp_path):
    source, sandbox = build_git_source(tmp_path)
    git(source, "switch", "-c", "feature")
    (source / "src" / "app.py").write_text("VALUE = 2\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "feature")

    with pytest.raises(RuntimeError, match="HEAD|checkout|base"):
        sandbox.prepare(mission_id="wrong-head")
