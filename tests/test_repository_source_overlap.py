from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_hq.config import Settings


def make_settings(
    *,
    sandbox: Path,
    ai_hq_source: Path,
    dripvid_source: Path,
) -> Settings:
    return Settings(
        database_url="sqlite:///test.db",
        redis_url="redis://127.0.0.1:6379/15",
        environment="development",
        repository_sandbox_root=str(sandbox),
        ai_hq_repository_source=str(ai_hq_source),
        dripvid_repository_source=str(dripvid_source),
    )


def test_disjoint_repository_sources_and_sandbox_are_allowed(
    tmp_path: Path,
):
    settings = make_settings(
        sandbox=tmp_path / "sandboxes",
        ai_hq_source=tmp_path / "sources" / "ai-hq",
        dripvid_source=tmp_path / "sources" / "dripvid",
    )

    assert settings.repository_sandbox_root_path == (
        tmp_path / "sandboxes"
    ).resolve()

    assert settings.ai_hq_repository_source_path == (
        tmp_path / "sources" / "ai-hq"
    ).resolve()

    assert settings.dripvid_repository_source_path == (
        tmp_path / "sources" / "dripvid"
    ).resolve()


@pytest.mark.parametrize(
    ("sandbox_relative", "source_relative"),
    [
        ("same", "same"),
        ("dripvid", "dripvid/source"),
        ("dripvid/source/sandboxes", "dripvid/source"),
    ],
)
def test_dripvid_source_must_not_overlap_repository_sandbox(
    tmp_path: Path,
    sandbox_relative: str,
    source_relative: str,
):
    sandbox = tmp_path / sandbox_relative
    dripvid_source = tmp_path / source_relative

    with pytest.raises(
        ValidationError,
        match=(
            "repository sandbox must not overlap "
            "the DripVid repository source"
        ),
    ):
        make_settings(
            sandbox=sandbox,
            ai_hq_source=tmp_path / "safe-ai-hq-source",
            dripvid_source=dripvid_source,
        )


@pytest.mark.parametrize(
    ("sandbox_relative", "source_relative"),
    [
        ("same", "same"),
        ("ai-hq", "ai-hq/source"),
        ("ai-hq/source/sandboxes", "ai-hq/source"),
    ],
)
def test_ai_hq_source_overlap_guard_remains_enforced(
    tmp_path: Path,
    sandbox_relative: str,
    source_relative: str,
):
    sandbox = tmp_path / sandbox_relative
    ai_hq_source = tmp_path / source_relative

    with pytest.raises(
        ValidationError,
        match=(
            "repository sandbox must not overlap "
            "the AI HQ repository source"
        ),
    ):
        make_settings(
            sandbox=sandbox,
            ai_hq_source=ai_hq_source,
            dripvid_source=tmp_path / "safe-dripvid-source",
        )
