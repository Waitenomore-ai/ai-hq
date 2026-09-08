import json
from pathlib import Path

import httpx

from ai_hq.code_changes.candidate_store import PersistedCandidate
from ai_hq.code_changes.publisher import (
    GitHubCandidatePublisher,
    build_default_publish_targets,
)


class Store:
    def read_changed_file(self, candidate, path):
        assert path == "src/example.py"
        return b"VALUE = 2\n"


def candidate():
    return PersistedCandidate(
        mission_id="mission-1",
        repository="ai-hq",
        workspace_id="11111111-1111-4111-8111-111111111111",
        base_ref="main",
        base_commit="1" * 40,
        change_ref="sha256:" + "a" * 64,
        changed_files=("src/example.py",),
        content_digest="sha256:" + "b" * 64,
        workspace_path=Path("/trusted/sandbox/ai-hq/workspace"),
    )


def test_recursive_tree_allows_normal_directory_entries():
    def handler(request):
        path = request.url.path
        if request.method == "GET" and path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "1" * 40}})
        if request.method == "GET" and "/git/commits/" in path:
            return httpx.Response(200, json={"tree": {"sha": "2" * 40}})
        if request.method == "GET" and "/git/trees/" in path:
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {
                            "path": "src",
                            "mode": "040000",
                            "type": "tree",
                            "sha": "3" * 40,
                        },
                        {
                            "path": "src/example.py",
                            "mode": "100644",
                            "type": "blob",
                            "sha": "4" * 40,
                        },
                    ],
                },
            )
        if request.method == "POST" and path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": "5" * 40})
        if request.method == "POST" and path.endswith("/git/trees"):
            body = json.loads(request.content)
            assert body["tree"] == [
                {
                    "path": "src/example.py",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "5" * 40,
                }
            ]
            return httpx.Response(201, json={"sha": "6" * 40})
        if request.method == "POST" and path.endswith("/git/commits"):
            return httpx.Response(
                201,
                json={"sha": "7" * 40, "tree": {"sha": "6" * 40}},
            )
        if request.method == "POST" and path.endswith("/git/refs"):
            return httpx.Response(201, json={"object": {"sha": "7" * 40}})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GitHubCandidatePublisher(
            http_client=client,
            token="test-token",
            candidate_store=Store(),
            targets=build_default_publish_targets(),
        ).publish(candidate())

    assert result.tree_sha == "6" * 40
    assert result.commit_sha == "7" * 40
