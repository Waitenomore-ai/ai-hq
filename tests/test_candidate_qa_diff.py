import json
from pathlib import Path

import pytest

from ai_hq.delivery.candidate_verifier import CandidateVerifier
from ai_hq.delivery.model_agents import ModelBackedQAAgent
from ai_hq.delivery.repository_profiles import (
    RepositoryProfile,
    RepositoryProfileRegistry,
)
from ai_hq.delivery.repository_sandbox import (
    IsolatedRepositorySandbox,
)
from ai_hq.delivery.repository_workspace import (
    CandidateSnapshot,
    FileChange,
    FileOperation,
    TestEvidence as WorkspaceTestEvidence,
)
from ai_hq.delivery.models import QAResult


def make_sandbox(
    tmp_path: Path,
) -> IsolatedRepositorySandbox:
    source = tmp_path / "source"
    source.mkdir()

    (source / "style.css").write_text(
        ".toolbar { min-height: 64px; }\n",
        encoding="utf-8",
    )

    profile = RepositoryProfile(
        key="dripvid",
        source_path=source,
        base_ref="main",
        test_commands=(("true",),),
    )

    registry = RepositoryProfileRegistry(
        (profile,)
    )

    return IsolatedRepositorySandbox(
        profile_registry=registry,
        repository_key="dripvid",
        sandbox_root=tmp_path / "sandboxes",
    )


def test_sandbox_produces_machine_derived_candidate_diff(
    tmp_path: Path,
):
    sandbox = make_sandbox(tmp_path)

    workspace = sandbox.prepare(
        mission_id="mission-1"
    )

    sandbox.apply_changes(
        workspace=workspace,
        changes=(
            FileChange(
                path="style.css",
                operation=FileOperation.WRITE,
                content=(
                    ".toolbar { min-height: 56px; }\n"
                ),
            ),
        ),
    )

    diff = sandbox.review_diff(
        workspace=workspace
    )

    assert "--- a/style.css" in diff
    assert "+++ b/style.css" in diff
    assert "-.toolbar { min-height: 64px; }" in diff
    assert "+.toolbar { min-height: 56px; }" in diff


def test_candidate_verifier_carries_machine_diff_in_evidence():
    verifier = CandidateVerifier()

    snapshot = CandidateSnapshot(
        workspace_id="workspace-1",
        repository="dripvid",
        base_ref="main",
        changed_files=("style.css",),
        diff_digest="sha256:" + ("a" * 64),
        content_digest="sha256:" + ("b" * 64),
    )

    tests = WorkspaceTestEvidence(
        passed=True,
        exit_code=0,
        summary="tests passed",
        evidence_digest="sha256:" + ("c" * 64),
    )

    candidate_diff = (
        "--- a/style.css\n"
        "+++ b/style.css\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    verified = verifier.verify(
        mission_id="mission-1",
        proposal={
            "summary": "Smaller toolbar",
        },
        snapshot=snapshot,
        test_evidence=tests,
        candidate_diff=candidate_diff,
    )

    assert (
        verified.evidence["candidate_diff"]
        == candidate_diff
    )

    digest = verified.evidence[
        "candidate_diff_digest"
    ]

    assert digest.startswith("sha256:")
    assert len(digest) == 71


class CapturingModel:
    def __init__(self):
        self.system_prompt = None
        self.messages = None

    def reply(
        self,
        system_prompt,
        messages,
    ):
        self.system_prompt = system_prompt
        self.messages = messages

        return json.dumps(
            {
                "result": "PASSED",
                "evidence": {
                    "review": (
                        "Reviewed machine-derived diff"
                    ),
                },
            }
        )


def test_qa_prompt_requires_machine_derived_diff_review():
    model = CapturingModel()

    agent = ModelBackedQAAgent(model)

    candidate_diff = (
        "--- a/style.css\n"
        "+++ b/style.css\n"
        "-old\n"
        "+new\n"
    )

    result = agent.review(
        mission_id="mission-1",
        change_ref="sha256:" + ("d" * 64),
        summary="Smaller toolbar",
        changed_files=["style.css"],
        developer_evidence={
            "verification": (
                "candidate_identity_verified"
            ),
            "candidate_diff": candidate_diff,
            "candidate_diff_digest": (
                "sha256:" + ("e" * 64)
            ),
            "tests": {
                "passed": True,
                "exit_code": 0,
            },
        },
    )

    assert result["result"] is QAResult.PASSED

    assert (
        "candidate_diff"
        in model.system_prompt
    )

    assert (
        "machine-derived"
        in model.system_prompt.casefold()
    )

    payload = json.loads(
        model.messages[0]["content"]
    )

    assert (
        payload["developer_evidence"][
            "candidate_diff"
        ]
        == candidate_diff
    )


def test_large_candidate_diff_fails_closed(
    tmp_path: Path,
):
    source = tmp_path / "source"
    source.mkdir()

    large_old = (
        "old-value-" * 3000
    )

    large_new = (
        "new-value-" * 3000
    )

    (source / "style.css").write_text(
        large_old,
        encoding="utf-8",
    )

    profile = RepositoryProfile(
        key="dripvid",
        source_path=source,
        base_ref="main",
        test_commands=(("true",),),
    )

    registry = RepositoryProfileRegistry(
        (profile,)
    )

    sandbox = IsolatedRepositorySandbox(
        profile_registry=registry,
        repository_key="dripvid",
        sandbox_root=tmp_path / "sandboxes",
    )

    workspace = sandbox.prepare(
        mission_id="mission-large"
    )

    with pytest.raises(
        ValueError,
        match="candidate review diff exceeds",
    ):
        sandbox.apply_changes(
            workspace=workspace,
            changes=(
                FileChange(
                    path="style.css",
                    operation=FileOperation.WRITE,
                    content=large_new,
                ),
            ),
        )
