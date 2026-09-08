import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from ai_hq.code_changes.candidate_store import CandidateStore


def manifest(root: Path) -> dict[str, str]:
    result = {}
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
                result[relative] = f"symlink:{os.readlink(path)}"
            elif path.is_file():
                result[relative] = "sha256:" + hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        for name in dirnames:
            path = directory_path / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                result[relative] = f"symlink:{os.readlink(path)}"
    return result


def digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_candidate(tmp_path: Path):
    root = tmp_path / "sandboxes"
    workspace_id = str(uuid4())
    workspace = root / "ai-hq" / workspace_id
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "changed.py").write_text("VALUE = 2\n")
    (workspace / "untouched.txt").write_text("same\n")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "ignored").write_text("ignored\n")

    content_digest = digest(manifest(workspace))
    diff_digest = "sha256:" + "c" * 64
    identity = {
        "mission_id": "mission-1",
        "repository": "ai-hq",
        "base_ref": "main",
        "base_commit": "b" * 40,
        "workspace_id": workspace_id,
        "changed_files": ["src/changed.py"],
        "diff_digest": diff_digest,
        "content_digest": content_digest,
    }
    change_ref = digest(identity)
    evidence = {
        "verification": "candidate_identity_verified",
        "algorithm": "sha256",
        "change_ref": change_ref,
        "workspace_id": workspace_id,
        "repository": "ai-hq",
        "base_ref": "main",
        "base_commit": "b" * 40,
        "diff_digest": diff_digest,
        "content_digest": content_digest,
    }
    return root, workspace, change_ref, evidence


def load(store, change_ref, evidence, *, changed_files=("src/changed.py",)):
    return store.load_verified(
        mission_id="mission-1",
        change_ref=change_ref,
        changed_files=changed_files,
        evidence=evidence,
    )


def test_store_reopens_exact_verified_workspace(tmp_path):
    root, workspace, change_ref, evidence = build_candidate(tmp_path)

    candidate = load(CandidateStore(root), change_ref, evidence)

    assert candidate.repository == "ai-hq"
    assert candidate.workspace_path == workspace.resolve()
    assert candidate.base_ref == "main"
    assert candidate.base_commit == "b" * 40
    assert candidate.changed_files == ("src/changed.py",)
    assert candidate.content_digest == evidence["content_digest"]


def test_store_reads_only_verified_changed_regular_files(tmp_path):
    root, _, change_ref, evidence = build_candidate(tmp_path)
    store = CandidateStore(root)
    candidate = load(store, change_ref, evidence)

    assert store.read_changed_file(candidate, "src/changed.py") == b"VALUE = 2\n"
    with pytest.raises(ValueError, match="changed file"):
        store.read_changed_file(candidate, "untouched.txt")


def test_store_represents_verified_deletion_as_none(tmp_path):
    root, _, _, evidence = build_candidate(tmp_path)
    changed_files = ("removed.txt",)
    identity = {
        "mission_id": "mission-1",
        "repository": evidence["repository"],
        "base_ref": evidence["base_ref"],
        "base_commit": evidence["base_commit"],
        "workspace_id": evidence["workspace_id"],
        "changed_files": list(changed_files),
        "diff_digest": evidence["diff_digest"],
        "content_digest": evidence["content_digest"],
    }
    change_ref = digest(identity)
    evidence["change_ref"] = change_ref
    store = CandidateStore(root)
    candidate = load(
        store,
        change_ref,
        evidence,
        changed_files=changed_files,
    )

    assert store.read_changed_file(candidate, "removed.txt") is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("change_ref", "sha256:" + "c" * 64, "change_ref"),
        ("repository", "unknown", "repository"),
        ("base_ref", "other", "base"),
        ("base_commit", "not-a-commit", "base"),
        ("workspace_id", "../escape", "workspace"),
        ("content_digest", "sha256:" + "d" * 64, "digest|change_ref"),
    ],
)
def test_store_fails_closed_on_tampered_machine_evidence(
    tmp_path, field, value, message
):
    root, _, change_ref, evidence = build_candidate(tmp_path)
    evidence[field] = value

    with pytest.raises((ValueError, KeyError), match=message):
        load(CandidateStore(root), change_ref, evidence)


def test_store_rejects_changed_files_that_do_not_match_change_ref(tmp_path):
    root, _, change_ref, evidence = build_candidate(tmp_path)

    with pytest.raises(ValueError, match="change_ref"):
        load(
            CandidateStore(root),
            change_ref,
            evidence,
            changed_files=("different.py",),
        )


def test_store_rejects_workspace_symlink(tmp_path):
    root, workspace, change_ref, evidence = build_candidate(tmp_path)
    real = tmp_path / "real-workspace"
    workspace.rename(real)
    workspace.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink|workspace"):
        load(CandidateStore(root), change_ref, evidence)


def test_store_rejects_workspace_content_changed_after_verification(tmp_path):
    root, workspace, change_ref, evidence = build_candidate(tmp_path)
    (workspace / "src" / "changed.py").write_text("MUTATED = True\n")

    with pytest.raises(ValueError, match="digest|stale"):
        load(CandidateStore(root), change_ref, evidence)


def test_store_rejects_unsafe_or_duplicate_changed_paths(tmp_path):
    root, _, change_ref, evidence = build_candidate(tmp_path)
    store = CandidateStore(root)

    for paths in (
        ("../escape",),
        (".git/config",),
        ("src/changed.py", "src/changed.py"),
    ):
        with pytest.raises(ValueError, match="changed|path"):
            load(store, change_ref, evidence, changed_files=paths)


def test_store_rejects_symlink_as_changed_file(tmp_path):
    root, workspace, _, evidence = build_candidate(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (workspace / "link.txt").symlink_to(outside)
    evidence["content_digest"] = digest(manifest(workspace))
    changed_files = ("link.txt",)
    identity = {
        "mission_id": "mission-1",
        "repository": evidence["repository"],
        "base_ref": evidence["base_ref"],
        "base_commit": evidence["base_commit"],
        "workspace_id": evidence["workspace_id"],
        "changed_files": list(changed_files),
        "diff_digest": evidence["diff_digest"],
        "content_digest": evidence["content_digest"],
    }
    change_ref = digest(identity)
    evidence["change_ref"] = change_ref

    store = CandidateStore(root)
    candidate = load(
        store,
        change_ref,
        evidence,
        changed_files=changed_files,
    )

    with pytest.raises(ValueError, match="regular|symlink"):
        store.read_changed_file(candidate, "link.txt")
