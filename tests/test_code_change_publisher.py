import inspect
import json
from pathlib import Path

import httpx
import pytest

from ai_hq.code_changes.candidate_store import PersistedCandidate
from ai_hq.code_changes.publisher import (
    CandidatePublisher,
    GitHubCandidatePublisher,
    PublishedCandidate,
    RepositoryPublishTarget,
    RepositoryPublishTargetRegistry,
    build_default_publish_targets,
    generated_branch_name,
)


def test_default_publish_targets_are_exact_and_trusted():
    registry = build_default_publish_targets()

    ai_hq = registry.get("ai-hq")
    dripvid = registry.get("dripvid")

    assert ai_hq == RepositoryPublishTarget(
        key="ai-hq",
        repository_full_name="Waitenomore-ai/ai-hq",
        base_branch="main",
        branch_prefix="ai-hq/candidate/",
    )
    assert dripvid == RepositoryPublishTarget(
        key="dripvid",
        repository_full_name="Waitenomore-ai/dripvid",
        base_branch="main",
        branch_prefix="ai-hq/candidate/",
    )

    with pytest.raises(KeyError, match="unknown publish target"):
        registry.get("other")


def test_registry_rejects_duplicate_repository_keys():
    target = RepositoryPublishTarget(
        key="ai-hq",
        repository_full_name="Waitenomore-ai/ai-hq",
        base_branch="main",
        branch_prefix="ai-hq/candidate/",
    )

    with pytest.raises(ValueError, match="duplicate"):
        RepositoryPublishTargetRegistry((target, target))


def test_generated_branch_name_is_deterministic_and_generated_only():
    target = build_default_publish_targets().get("ai-hq")
    change_ref = "sha256:" + "a" * 64

    first = generated_branch_name(
        target,
        mission_id="mission user supplied / unsafe",
        change_ref=change_ref,
    )
    second = generated_branch_name(
        target,
        mission_id="mission user supplied / unsafe",
        change_ref=change_ref,
    )

    assert first == second
    assert first.startswith("ai-hq/candidate/")
    assert "mission user supplied" not in first
    assert " " not in first
    assert "/unsafe" not in first
    assert first.endswith("-" + "a" * 12)


def test_generated_branch_name_changes_with_mission_or_candidate():
    target = build_default_publish_targets().get("ai-hq")

    first = generated_branch_name(
        target,
        mission_id="mission-a",
        change_ref="sha256:" + "a" * 64,
    )
    second = generated_branch_name(
        target,
        mission_id="mission-b",
        change_ref="sha256:" + "a" * 64,
    )
    third = generated_branch_name(
        target,
        mission_id="mission-a",
        change_ref="sha256:" + "b" * 64,
    )

    assert len({first, second, third}) == 3


def test_published_candidate_requires_machine_identities():
    result = PublishedCandidate(
        repository="ai-hq",
        change_ref="sha256:" + "a" * 64,
        branch_name="ai-hq/candidate/123456789abc-aaaaaaaaaaaa",
        commit_sha="b" * 40,
        tree_sha="c" * 40,
        base_commit="d" * 40,
    )

    assert result.commit_sha == "b" * 40

    with pytest.raises(ValueError, match="commit"):
        PublishedCandidate(
            repository="ai-hq",
            change_ref="sha256:" + "a" * 64,
            branch_name="ai-hq/candidate/x",
            commit_sha="bad",
            tree_sha="c" * 40,
            base_commit="d" * 40,
        )


def test_publisher_protocol_exposes_no_remote_ref_or_force_authority():
    signature = inspect.signature(CandidatePublisher.publish)
    assert set(signature.parameters) == {"self", "candidate"}

    names = set(dir(CandidatePublisher))
    assert "publish" in names
    assert "force" not in names
    assert "update_ref" not in names
    assert "set_remote" not in names
    assert "run_git" not in names


class FakeCandidateStore:
    def __init__(self, files):
        self.files = files
        self.reads = []

    def read_changed_file(self, candidate, path):
        self.reads.append(path)
        return self.files[path]


def candidate(*, base_commit="1" * 40, changed_files=("script.sh", "src/new.py", "old.txt")):
    return PersistedCandidate(
        mission_id="mission-123",
        repository="ai-hq",
        workspace_id="11111111-1111-4111-8111-111111111111",
        base_ref="main",
        base_commit=base_commit,
        change_ref="sha256:" + "a" * 64,
        changed_files=changed_files,
        content_digest="sha256:" + "b" * 64,
        workspace_path=Path("/trusted/sandbox/ai-hq/workspace"),
    )


def github_responder(request, *, stale=False, unsafe_mode=None, fail_path=None):
    path = request.url.path
    method = request.method
    if fail_path and fail_path in path:
        return httpx.Response(500, json={"message": "provider failure"})
    if method == "GET" and path.endswith("/git/ref/heads/main"):
        return httpx.Response(200, json={"object": {"sha": ("9" if stale else "1") * 40}})
    if method == "GET" and "/git/commits/" in path:
        return httpx.Response(200, json={"sha": "1" * 40, "tree": {"sha": "2" * 40}})
    if method == "GET" and "/git/trees/" in path:
        mode = unsafe_mode or "100755"
        return httpx.Response(
            200,
            json={
                "sha": "2" * 40,
                "truncated": False,
                "tree": [
                    {"path": "script.sh", "mode": mode, "type": "blob", "sha": "3" * 40},
                    {"path": "old.txt", "mode": "100644", "type": "blob", "sha": "4" * 40},
                ],
            },
        )
    if method == "POST" and path.endswith("/git/blobs"):
        body = json.loads(request.content)
        if body["content"] == "bmV3IHNjcmlwdAo=":
            return httpx.Response(201, json={"sha": "5" * 40})
        return httpx.Response(201, json={"sha": "6" * 40})
    if method == "POST" and path.endswith("/git/trees"):
        body = json.loads(request.content)
        assert body["base_tree"] == "2" * 40
        entries = {entry["path"]: entry for entry in body["tree"]}
        assert entries["script.sh"] == {
            "path": "script.sh",
            "mode": "100755",
            "type": "blob",
            "sha": "5" * 40,
        }
        assert entries["src/new.py"] == {
            "path": "src/new.py",
            "mode": "100644",
            "type": "blob",
            "sha": "6" * 40,
        }
        assert entries["old.txt"] == {
            "path": "old.txt",
            "mode": "100644",
            "type": "blob",
            "sha": None,
        }
        return httpx.Response(201, json={"sha": "7" * 40})
    if method == "POST" and path.endswith("/git/commits"):
        body = json.loads(request.content)
        assert body["tree"] == "7" * 40
        assert body["parents"] == ["1" * 40]
        assert "mission-123" not in body["message"]
        return httpx.Response(201, json={"sha": "8" * 40, "tree": {"sha": "7" * 40}})
    if method == "POST" and path.endswith("/git/refs"):
        body = json.loads(request.content)
        assert body["ref"].startswith("refs/heads/ai-hq/candidate/")
        assert body["sha"] == "8" * 40
        assert "force" not in body
        return httpx.Response(201, json={"ref": body["ref"], "object": {"sha": "8" * 40}})
    raise AssertionError(f"unexpected GitHub request: {method} {path}")


def test_github_publisher_creates_exact_candidate_tree_and_generated_ref():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-publisher-token"
        return github_responder(request)

    store = FakeCandidateStore(
        {
            "script.sh": b"new script\n",
            "src/new.py": b"VALUE = 1\n",
            "old.txt": None,
        }
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GitHubCandidatePublisher(
            http_client=client,
            token="test-publisher-token",
            candidate_store=store,
            targets=build_default_publish_targets(),
        ).publish(candidate())

    assert result.repository == "ai-hq"
    assert result.base_commit == "1" * 40
    assert result.commit_sha == "8" * 40
    assert result.tree_sha == "7" * 40
    assert result.branch_name.startswith("ai-hq/candidate/")
    assert store.reads == ["old.txt", "script.sh", "src/new.py"]
    assert not any(request.method == "PATCH" for request in requests)


def test_github_publisher_fails_before_mutation_when_remote_main_is_stale():
    requests = []

    def handler(request):
        requests.append(request)
        return github_responder(request, stale=True)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        publisher = GitHubCandidatePublisher(
            http_client=client,
            token="token-value",
            candidate_store=FakeCandidateStore({}),
            targets=build_default_publish_targets(),
        )
        with pytest.raises(RuntimeError, match="stale|base"):
            publisher.publish(candidate())

    assert [request.method for request in requests] == ["GET"]


@pytest.mark.parametrize("unsafe_mode", ["120000", "160000"])
def test_github_publisher_rejects_symlink_or_submodule_base_entries(unsafe_mode):
    def handler(request):
        return github_responder(request, unsafe_mode=unsafe_mode)

    store = FakeCandidateStore(
        {"script.sh": b"new script\n", "src/new.py": b"x", "old.txt": None}
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        publisher = GitHubCandidatePublisher(
            http_client=client,
            token="token-value",
            candidate_store=store,
            targets=build_default_publish_targets(),
        )
        with pytest.raises(RuntimeError, match="symlink|submodule|mode|blob"):
            publisher.publish(candidate())


def test_github_publisher_rejects_zero_or_missing_base_commit_and_token():
    store = FakeCandidateStore({})
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail("network called"))) as client:
        with pytest.raises(ValueError, match="token"):
            GitHubCandidatePublisher(
                http_client=client,
                token="",
                candidate_store=store,
                targets=build_default_publish_targets(),
            )

        publisher = GitHubCandidatePublisher(
            http_client=client,
            token="token-value",
            candidate_store=store,
            targets=build_default_publish_targets(),
        )
        with pytest.raises(ValueError, match="base commit"):
            publisher.publish(candidate(base_commit="0" * 40))


def test_github_publisher_fails_closed_on_provider_error_without_secret_leak():
    def handler(request):
        return github_responder(request, fail_path="git/ref/heads/main")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        publisher = GitHubCandidatePublisher(
            http_client=client,
            token="super-secret-token",
            candidate_store=FakeCandidateStore({}),
            targets=build_default_publish_targets(),
        )
        with pytest.raises(RuntimeError) as exc_info:
            publisher.publish(candidate())

    assert "super-secret-token" not in str(exc_info.value)
    assert "provider failure" not in str(exc_info.value)
