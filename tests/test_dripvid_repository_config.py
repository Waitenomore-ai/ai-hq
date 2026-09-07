from pathlib import Path

from ai_hq.config import Settings


def base_settings(**overrides):
    values = {
        "database_url": "sqlite:///test.db",
        "redis_url": "redis://localhost/0",
        "environment": "development",
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_expose_dripvid_repository_source(tmp_path: Path):
    settings = base_settings(
        dripvid_repository_source=str(tmp_path)
    )

    assert (
        settings.dripvid_repository_source_path
        == tmp_path.resolve()
    )


def test_repository_sources_can_share_sandbox_only_when_non_overlapping(
    tmp_path: Path,
):
    ai_hq = tmp_path / "ai-hq"
    dripvid = tmp_path / "dripvid"
    sandbox = tmp_path / "sandboxes"

    ai_hq.mkdir()
    dripvid.mkdir()

    settings = base_settings(
        ai_hq_repository_source=str(ai_hq),
        dripvid_repository_source=str(dripvid),
        repository_sandbox_root=str(sandbox),
    )

    assert settings.ai_hq_repository_source_path == ai_hq.resolve()
    assert settings.dripvid_repository_source_path == dripvid.resolve()
