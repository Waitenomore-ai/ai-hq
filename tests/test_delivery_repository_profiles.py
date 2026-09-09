from pathlib import Path

import pytest

from ai_hq.delivery.repository_profiles import (
    TRUSTED_REPOSITORY_KEYS,
    RepositoryProfileRegistry,
    build_ai_hq_repository_profile,
    build_dripvid_repository_profile,
)


def test_trusted_repository_keys_are_centralized():
    assert TRUSTED_REPOSITORY_KEYS == frozenset({"ai-hq", "dripvid"})


def test_ai_hq_profile_has_description(tmp_path):
    profile = build_ai_hq_repository_profile(source_path=tmp_path)

    assert profile.description
    assert "AI HQ" in profile.description


def test_dripvid_profile_has_description(tmp_path):
    profile = build_dripvid_repository_profile(source_path=tmp_path)

    assert profile.description
    assert "DripVid" in profile.description


def test_ai_hq_profile_has_fixed_trusted_test_commands(tmp_path):
    profile = build_ai_hq_repository_profile(source_path=tmp_path)

    assert profile.key == "ai-hq"
    assert profile.source_path == tmp_path.resolve()
    assert profile.base_ref == "main"
    assert len(profile.test_commands) == 2
    assert profile.test_commands[0][1:4] == ("-m", "ruff", "check")
    assert profile.test_commands[1][1:3] == ("-m", "pytest")


def test_unknown_repository_fails_closed(tmp_path):
    registry = RepositoryProfileRegistry(
        (build_ai_hq_repository_profile(source_path=tmp_path),)
    )

    with pytest.raises(KeyError, match="unknown repository"):
        registry.get("dripvid")


def test_profile_registry_rejects_duplicate_keys(tmp_path):
    profile = build_ai_hq_repository_profile(source_path=tmp_path)

    with pytest.raises(ValueError, match="duplicate"):
        RepositoryProfileRegistry((profile, profile))


def test_profile_requires_existing_directory(tmp_path):
    missing = Path(tmp_path) / "missing"

    with pytest.raises(ValueError, match="source"):
        build_ai_hq_repository_profile(source_path=missing)


def test_profile_rejects_untrusted_repository_key(tmp_path):
    from ai_hq.delivery.repository_profiles import RepositoryProfile

    with pytest.raises(
        ValueError,
        match="registered trusted repository",
    ):
        RepositoryProfile(
            key="pinokio",
            source_path=tmp_path,
            base_ref="main",
            description="Untrusted example repository",
            test_commands=(("true",),),
        )


def test_profile_description_must_be_string(tmp_path):
    from ai_hq.delivery.repository_profiles import RepositoryProfile

    with pytest.raises(TypeError, match="description"):
        RepositoryProfile(
            key="ai-hq",
            source_path=tmp_path,
            base_ref="main",
            description=None,
            test_commands=(("true",),),
        )
