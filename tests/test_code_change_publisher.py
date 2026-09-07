import inspect

import pytest

from ai_hq.code_changes.publisher import (
    CandidatePublisher,
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
