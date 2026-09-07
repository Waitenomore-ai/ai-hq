from pathlib import Path

import pytest

from ai_hq.delivery.repository_profiles import (
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
    build_dripvid_repository_profile,
)


def test_dripvid_profile_has_trusted_identity_and_fixed_tests(tmp_path: Path):
    profile = build_dripvid_repository_profile(
        source_path=tmp_path,
        base_ref="main",
    )

    assert profile.key == "dripvid"
    assert profile.source_path == tmp_path.resolve()
    assert profile.base_ref == "main"
    assert profile.test_commands == (
        ("npm", "run", "check"),
        ("npm", "test"),
    )


def test_registry_resolves_only_configured_logical_repository_keys(
    tmp_path: Path,
):
    ai_hq_path = tmp_path / "ai-hq"
    dripvid_path = tmp_path / "dripvid"
    ai_hq_path.mkdir()
    dripvid_path.mkdir()

    registry = RepositoryProfileRegistry(
        (
            build_ai_hq_repository_profile(
                source_path=ai_hq_path,
                base_ref="HEAD",
            ),
            build_dripvid_repository_profile(
                source_path=dripvid_path,
                base_ref="main",
            ),
        )
    )

    assert registry.get("ai-hq").key == "ai-hq"
    assert registry.get("dripvid").key == "dripvid"

    with pytest.raises(KeyError, match="unknown repository"):
        registry.get("some-random-repository")


def test_dripvid_verification_commands_do_not_come_from_user_input(
    tmp_path: Path,
):
    malicious_text = "rm -rf /"

    profile = build_dripvid_repository_profile(
        source_path=tmp_path,
        base_ref="main",
    )

    flattened = " ".join(
        part
        for command in profile.test_commands
        for part in command
    )

    assert malicious_text not in flattened
    assert profile.test_commands == (
        ("npm", "run", "check"),
        ("npm", "test"),
    )
